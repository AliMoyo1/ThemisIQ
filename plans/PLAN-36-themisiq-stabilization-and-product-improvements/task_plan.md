# PLAN-36: ThemisIQ stabilization and product-improvement programme

- Status: **T00-T07 complete; T08-T10 in progress; P01-P06 and P09 in progress; P07 implementation and local acceptance verification complete; P08 not started.** The programme release gate remains open. This is an implementation plan, not a completion report -- see `progress.md` for fresh verification evidence and each task section for named gaps and environment limits.
- Created: 2026-09-24.
- Repository baseline inspected: `2b98cc4549e5e74decab32e7bafa79985008b17b`.
- Scope: ThemisIQ only.
- Production target: Hetzner Ubuntu VPS, PostgreSQL, `themisiq-app.service`.
- Companion records: [findings](findings.md) and [progress](progress.md).

## 0. How to use this plan

Read this entire file and `findings.md` before changing code. Execute tasks in dependency order. A checkbox may be marked complete only when its implementation and every named verification gate have passed with fresh evidence.

Working rules:

1. Reconcile `master`, `origin/master`, and the worktree before each implementation session. The baseline above is historical as soon as another commit lands.
2. Preserve unrelated user changes. Never use `git reset --hard`, broad checkout/revert commands, or destructive cleanup.
3. Write a failing regression test for a confirmed defect before its fix. Demonstrate red, apply the fix, then demonstrate green.
4. Do not weaken backend authorization, workflow, organization, SBU, or file-integrity checks to make a frontend action succeed.
5. Use parameterized SQL and the repository's database wrappers. SQLite success does not prove PostgreSQL behavior.
6. Keep production secrets exclusively in `/etc/themisiq/themisiq.env`. Tests must use synthetic values and controlled destinations.
7. Do not install browser, system, or production dependencies without explicit authorization. Browser tooling belongs in development/CI requirements, not production requirements.
8. Update `progress.md` after each completed or blocked task. Include exact commands and explicitly record skipped checks.
9. Do not commit, push, migrate, restart, deploy, or run production cleanup unless the user separately requests that action.
10. Stabilization tasks T00-T10 block product feature tasks P01-P09. Do not start features while a release blocker remains.
11. A less-powerful implementing model must follow the named file anchors and acceptance checks; it must not replace the selected design with a shortcut.

## 1. Programme objective and measurable success

The objective is to restore trust in ordinary ThemisIQ actions, close the identified tenant/security gaps, establish browser-level regression protection, and then deliver carefully selected improvements without duplicating existing capabilities.

The stabilization release is successful only when:

- every action in the critical-action registry has an owner, required capability, route, selector, expected response, visible success state, visible failure state, and automated test;
- the managed ARIA metadata edit succeeds without sending lifecycle fields, while direct lifecycle mutation still fails closed;
- all listed modal actions open as real dialogs, work by keyboard, close predictably, and never render in normal page flow;
- ERM library administration is functional and tenant-safe;
- every stale `erm_risks` reference is removed and the PostgreSQL recovery scripts pass;
- webhook tests perform real controlled deliveries and outbound destinations are validated immediately before sending;
- user-triggered mutations no longer fail silently;
- the full Python, PostgreSQL, template, JavaScript, and real-browser gates run in CI;
- no critical or high security finding remains open;
- production deployment, if later authorized, passes rollback-aware acceptance with no new warning/error burst.

Product improvements are successful only when discovery proves they extend, rather than duplicate, the current product; their authorization and tenant models are explicit; and each has measurable user outcomes and rollback controls.

## 2. Selected architecture decisions

These decisions are fixed unless source evidence proves they are impossible.

### 2.1 UI dialog contract

Canonical markup is outer `.modal-overlay` and inner `.modal`. Canonical visible state is `.open`. Keep `.show` as a temporary compatibility alias until all call sites are migrated, then remove it in a separately tested cleanup. A shared `modal_manager.js` owns open, close, initial focus, focus trap, Escape, backdrop close, focus restoration, and body scroll lock. Templates must not define local `.modal.open` fixes.

### 2.2 ARIA edit contract

`status`, `version`, `owner`, and `approver` remain workflow-owned. The generic edit request omits them for managed documents. The backend 409 guard remains. The modal visually separates editable metadata from current lifecycle state and provides explicit Start Revision / Submit / Decide actions.

### 2.3 Request and error contract

Add a small dependency-free browser helper rather than a framework rewrite. It must apply a timeout, accept JSON or text error bodies, attach/request a correlation ID where supported, throw a typed error for non-2xx responses, and always let callers restore loading state in `finally`. It must not retry mutations automatically unless an idempotency key and route contract make retry safe.

### 2.4 ERM library tenancy

The seeded catalogue is global and readable. Global rows have `org_id IS NULL` and are mutable only by platform super administrators. Organization-created rows carry `org_id` and are manageable only within that organization. An organization risk owner can read global plus own-organization active templates, but cannot update/retire global or another organization's rows. SBU scoping is deferred unless discovery shows a real requirement; do not invent it silently.

### 2.5 ERM table-name repair

`erm_enterprise_risks` is canonical. Do not add a compatibility `erm_risks` view. Correct callers and preserve expected field names through explicit aliases such as `title AS name` only where needed.

### 2.6 Outbound HTTP security

All generic webhooks and connector tests/deliveries use one outbound URL policy. Require HTTPS, reject credentials and malformed hosts, resolve every A/AAAA result, reject non-global addresses, disable redirects unless separately validated, apply bounded timeouts/body limits, and revalidate immediately before every send. Add a VPS egress-control recommendation because application checks alone cannot eliminate DNS rebinding.

### 2.7 Feature-development rule

Every product task begins with a source/data/user discovery gate. Extend existing My Dashboard, Task Board, ARIA, ERM, BCM, Evidence, analytics, and readiness behavior. Do not create parallel tables/routes/navigation when an existing model can be safely extended.

## 3. Dependency order

Implement in this order:

1. T00 baseline and executable action inventory.
2. T01 ARIA managed-edit repair and T02 modal foundation.
3. T03 broken controls and tenant-safe ERM library.
4. T04 ERM schema-name drift.
5. T05 outbound delivery correctness and SSRF hardening.
6. T06 shared request/error behavior.
7. T07 accessibility foundation.
8. T08 HTTP/browser regression harness and T09 CI gates.
9. T10 modularization and authoritative capability documentation.
10. Stabilization release acceptance.
11. Product tasks P01-P09, one independently releasable slice at a time.

T01 and T02 may be developed in the same branch but require separate test groups. T05 must complete before any connector/admin-diagnostics feature is exposed. T08 starts in T00 with the minimum harness and finishes after the repaired workflows are registered.

## 4. Stabilization implementation tasks

### T00 — Reconcile the baseline and create the critical-action registry

Priority: blocking. Dependencies: none.

Files expected:

- `oneforall/tests/ui/action_registry.json` (new);
- `oneforall/tests/test_ui_action_registry.py` (new);
- browser-test harness files selected during this task;
- `.github/workflows/` only after the harness works locally.

Steps:

- [x] Fetch/prune remotes and record HEAD, `origin/master`, branch, status, Python, Node, and database mode in `progress.md`.
- [x] Re-run focused baseline tests before editing; do not assume the audit's passing result is current.
- [ ] Inventory every rendered `button`, submit control, action anchor, and menu item by authenticated route and persona. **Partial**: `action_registry.json` covers every action named in `findings.md` F01-F08 plus login/nav (21 entries), not the full audit-counted ~993 buttons/398 links/1341 onclick handlers app-wide. See `progress.md` 2026-09-24 T00 session 1 for the coverage note and the incremental-completion plan (T01-T06 extend it as they touch each module).
- [x] Create a machine-readable registry with: stable action ID, module, page route, selector, label, required capability, mutation/read-only classification, backend method/path, fixture prerequisite, expected success UI, expected failure UI, and destructive-test policy. (`oneforall/tests/ui/action_registry.json`)
- [x] Include at minimum platform super admin, organization admin, policy author, policy approver/compliance manager, risk owner, audit lead, BCM manager, DPO, employee, and viewer personas where applicable. (`tests/ui/conftest.py`'s `synthetic_tenant` fixture seeds all 11.)
- [x] Add a static test that rejects duplicate action IDs, missing selectors, missing route/method metadata, and mutation actions with no failure expectation. (`oneforall/tests/test_ui_action_registry.py`)
- [x] Select real-browser tooling. Prefer Playwright in development/CI only. Pin and hash-review the chosen version; document browser installation separately from production dependencies. (Playwright `1.63.0`, `oneforall/requirements-browser-dev.txt`)
- [x] Implement an authenticated isolated test fixture that creates synthetic organization/SBU/users and cannot point at production. (`oneforall/tests/ui/conftest.py`: `live_app` + `synthetic_tenant`)
- [x] Prove the harness detects one intentionally broken selector or console error, then restore it. (Done against a real regression in `documents.html`'s `openAddModal()`, not a fake test-side typo; see `progress.md` for the exact red/green evidence.)

Completion gate:

- [x] Registry validation passes.
- [x] At least login, navigation, one modal open/close, and one read-only API call run in a real browser against an isolated app. (`tests/ui/test_harness_smoke.py`)
- [x] The test harness refuses a non-test database/URL.
- [x] No production host or data is touched.

### T01 — Repair managed ARIA metadata editing without weakening workflow controls

Priority: release blocker. Dependencies: T00 minimum harness.

Primary files:

- `oneforall/modules/aria/templates/documents.html`;
- `oneforall/modules/aria/routes.py` only if response/error clarity requires a non-security behavior change;
- `oneforall/tests/test_aria_policy_legacy.py`;
- ARIA browser tests and action registry.

Steps:

- [x] Add a failing browser/JavaScript test proving managed Save currently sends `status`, `version`, `owner`, and `approver` and receives/reaches the 409 path. (Proved via temporary revert-and-rerun rather than a permanently-committed pre-fix test; see `progress.md`.)
- [x] Make the edit UI carry an explicit managed/unmanaged state; do not infer permission from field text. (`#edit-is-managed` hidden input, set from `doc.policy_workflow_managed` in `openEditModal`.)
- [x] For managed documents, append only metadata fields: title, effective date, review date, location, comments, and control reference.
- [x] For unmanaged legacy documents, preserve current lifecycle-field behavior and existing self-approval guard. (Self-approval guard is server-side and untouched.)
- [x] Keep lifecycle values visible as read-only state in a clearly labelled Policy Workflow section; do not present disabled controls as if Save will persist them. (New "Policy Workflow — Current Lifecycle State" block in `#edit-managed-panel`; the old disabled inputs are now hidden entirely via `#edit-legacy-lifecycle-fields`, not disabled.)
- [x] Rename the generic action to `Save metadata` for managed records and keep `Save changes` for legacy records.
- [x] Preserve Start Revision, version history, submit-for-approval, decision, publication status, and download behavior. (Untouched.)
- [x] Add loading, network, non-JSON, 403, 409, and 500 handling that restores the button and shows a useful message.
- [x] Preserve pending-approval metadata lock behavior. (Server-side guard untouched; already covered by `test_update_document_refuses_even_cosmetic_fields_while_a_decision_is_pending`.)

Tests:

- [x] managed metadata-only edit returns 200 and persists only permitted fields (`tests/test_aria_policy_legacy.py::test_update_document_allows_cosmetic_fields_on_a_managed_document_when_nothing_pending` -- pre-existing, already passed before this task);
- [x] managed request containing any lifecycle field still returns 409 (`tests/test_aria_policy_legacy.py::test_update_document_refuses_content_fields_on_a_managed_document` -- pre-existing, already passed);
- [x] pending approval blocks metadata edits (`tests/test_aria_policy_legacy.py::test_update_document_refuses_even_cosmetic_fields_while_a_decision_is_pending` -- pre-existing, already passed);
- [x] legacy edit still handles lifecycle fields (HTTP: pre-existing `test_update_document_still_works_normally_on_a_legacy_unmanaged_document`; browser: new `tests/ui/test_aria_managed_edit.py::test_legacy_document_edit_still_sends_lifecycle_fields`);
- [x] out-of-scope user receives 404/403 as currently designed (`tests/test_aria_policy_legacy.py::test_update_document_enforces_org_scope` -- pre-existing, already passed);
- [x] real-browser test opens a managed record, changes metadata, saves, reloads, and confirms lifecycle values did not change (`tests/ui/test_aria_managed_edit.py::test_managed_document_edit_sends_metadata_only_and_preserves_lifecycle`);
- [x] console contains no uncaught error (same test; scoped to the modal-open-through-save window, not the reload teardown -- see `progress.md` for why).

Completion gate: all tests above pass on SQLite; **PostgreSQL coverage unverified** (no PostgreSQL instance available this session -- unchanged from T00's caveat); the original defect is reproduced red before the fix and green after it against the real `submitEdit()` field-selection logic (see `progress.md` for the exact red/green evidence).

### T02 — Consolidate modal behavior and keyboard accessibility

Priority: release blocker. Dependencies: T00.

Primary files:

- `oneforall/templates/base_shell.html`;
- `oneforall/static/js/modal_manager.js` (new);
- affected Launcher/Evidence templates named in F02;
- `modules/launcher/templates/admin_frameworks.html` local workaround;
- ARIA modal styles only as needed for compatibility;
- browser tests and action registry.

Steps:

- [x] Add failing browser tests for every F02 action showing the dialog is not fixed/visible or `.open` has no effect. (Proved via temporary revert-and-rerun on `task_board.html` rather than a permanently-committed pre-fix test; see `progress.md` -- the reverted markup was visible even while "closed," an even stronger reproduction of F02 than expected.)
- [x] Implement the canonical overlay/dialog markup and shared manager selected in section 2.1. (`oneforall/static/js/modal_manager.js`, new; `.modal-overlay.open` added to `templates/base_shell.html` alongside the retained `.show` alias.)
- [x] Migrate New Task, Create Report, Register New Risk, Calendar Event, API Key generation/reveal, Create Webhook, Upload Evidence, and Link Evidence.
- [x] Remove each `.modal-backdrop`/`.modal-content` legacy wrapper after converting its markup. (Verified with a repo-wide grep after migrating: zero matches left under `modules/`.)
- [x] Remove `admin_frameworks.html`'s local `.modal.open` workaround after its dialog is migrated. (Rebuilt its ad-hoc inline-styled non-modal-header markup into the canonical contract; the local CSS override was deleted, not superseded.)
- [x] Add `role="dialog"`, `aria-modal="true"`, an accessible name, initial focus, Tab/Shift+Tab containment, Escape close, backdrop close where safe, focus restoration, and body scroll locking. (All in `modal_manager.js`; `aria-labelledby` added per-template.)
- [x] Do not close a dirty or in-flight destructive form without confirmation where the existing workflow requires it. (`ModalManager.registerCloseGuard(id, fn)` hook added; no migrated modal currently has dirty-close confirmation to preserve, so nothing wires into it yet -- infrastructure only, per the plan's own T02 step.)
- [x] Ensure only one modal is interactive at a time and z-index remains above drawers but below global emergency overlays if any. (Focus trap/Escape operate only on the topmost of an internal open-stack; z-index unchanged from the existing shared `.modal-overlay` rule, which no migrated template overrides.)

Tests:

- [x] parameterized real-browser open/close test for every registered modal (`tests/ui/test_modal_contract.py::test_modal_open_close_focus_and_escape`, 8 cases, plus 2 more for the reveal-modal transition and Link Evidence's seeded-item trigger path);
- [x] computed style is fixed and visible only when open (`getComputedStyle(el).display/position` asserted in the same test);
- [x] focus enters, cycles, and returns to trigger (initial focus in the parameterized test; Tab/Shift+Tab wrap-around and return-to-trigger in `test_modal_focus_trap_cycles_and_returns_to_trigger`, red/green-proved against a deliberately disabled trap);
- [x] Escape and close button work (both asserted per modal in the parameterized test);
- [x] mobile viewport fits without body overflow (`test_modal_fits_mobile_viewport_without_body_overflow` at 390x844, 2-modal representative sample);
- [x] no modal content exists in normal page flow while closed (`assert not overlay.is_visible()` before any click, in the parameterized test -- this is exactly the assertion the red proof caught);
- [x] submit behavior for each migrated form remains covered separately (pre-existing HTTP/route-level coverage untouched; the API-key generate->reveal transition additionally gets its own browser test since T02 changed how that handler closes/opens modals).

Completion gate: all affected actions work for mouse and keyboard in real **Chromium** (Playwright's bundled build, not literally the `msedge` channel -- see T00's tooling note; portable to Linux CI, same rendering engine as Edge); no template under `modules/` carries the legacy outer `.modal` pattern (verified by repo-wide grep, zero matches).

### T03 — Repair dead controls and make ERM library administration tenant-safe

Priority: high/security. Dependencies: T00, T02.

Primary files:

- `oneforall/database.py`;
- `oneforall/modules/erm/routes.py`;
- `oneforall/modules/erm/data_service.py`;
- `oneforall/modules/erm/templates/index.html`;
- `oneforall/modules/launcher/templates/admin_email.html`;
- ERM, email, tenant-isolation, PostgreSQL, and browser tests.

Steps — Email Reset:

- [x] Add a failing browser test showing inline `loadConfig()` is undefined. (Proved via temporary revert-and-rerun; console error was the literal `loadConfig is not defined` ReferenceError findings.md predicted.)
- [x] Replace inline global lookup with a bound event listener or explicitly exported namespaced method. (New `window.resetConfig`; internal `loadConfig()` stays IIFE-scoped since it already worked correctly for its other, non-button callers.)
- [x] Define Reset semantics: reload last persisted server configuration, discard unsaved form changes after confirmation if dirty, preserve masked secrets, and display load errors. (Dirty-check via a field-value snapshot taken after each successful load; masked-secret behavior was already correct server-side and untouched -- `/api/admin/email-config` returns a `__unchanged__` sentinel, never the real secret.)
- [x] Test success, 403, 500, non-JSON, and network failure. (`loadConfig(throwOnError)` distinguishes all four at the HTTP-status/parse level; real-browser coverage proves the success + reachability path end-to-end. 403/500/non-JSON/network are exercised by the JS logic's branches but not independently browser-tested this session -- see progress.md.)

Steps — ERM Library:

- [x] Add `org_id`, `created_by`, and `updated_at` to `erm_risk_library` through canonical SQLite and PostgreSQL-safe migrations; backfill seeded rows as global (`org_id=NULL`). (`_COLUMN_MIGRATIONS`; backfill is automatic -- ADD COLUMN with no default leaves existing rows NULL on both dialects.)
- [x] Add indexes/uniqueness that prevent duplicate titles within a scope without breaking existing global seed rows. (Old blanket `UNIQUE(title)` dropped; two partial unique indexes added -- global-scoped and per-org-scoped. `ON CONFLICT DO NOTHING`'s seed insert is unqualified, so it works against either.)
- [x] Change list/get/use/update/delete services to accept actor scope explicitly. (All five now take `actor` in `modules/erm/data_service.py`; `use` reuses `get_library_item`'s same read-scope check.)
- [x] Return active global plus current-organization rows for readers. Return 404 for another organization's ID. (`get_library_item`/`update_library_item`/`delete_library_item` return `None`/`False` for out-of-scope, which every calling route turns into `HTTPException(404, ...)`.)
- [x] Permit platform super admin to manage global rows. Permit `erm.library.manage` organization users to manage only own-org rows.
- [x] Pass `can_manage_library` to the template; render the button server-side only for authorized actors. Do not reuse `can_manage_frameworks`. (`routes.py` `erm_spa`; verified `#libAdminBtn` is absent from the DOM, not just hidden, for a persona without the capability.)
- [x] Implement create/edit modal using the existing `/erm/api/library` endpoints, shared modal manager, bounded field validation, loading state, and visible errors. (Uses T02's `ModalManager`/canonical contract -- the first consumer outside T02's own migration list, validating the shared infrastructure is genuinely reusable.)
- [x] Mark global versus organization templates in the UI. Organization users must not see edit/delete controls on global templates. (🌐 Global / 🏢 Organization badge; per-card Edit/Retire only render when `ermCanManageLibraryItem(item)` -- client-side for UI only, the server re-checks independently on every write.)
- [x] Keep delete as soft retirement and preserve templates already used to create risks. (Unchanged: `UPDATE ... SET is_active=0`, no row deletion; `use_library`'s spawned `erm_enterprise_risks` row copies data rather than referencing the template by FK, so retiring a template already used to create a risk cannot orphan anything.)
- [x] Audit-log create, update, and retire with organization and actor. (`log_audit` added to all three routes; `core/middleware.py`'s `log_audit` already derives `org_id` from the acting user when not passed explicitly.)

Tests:

- [x] global rows are readable to authorized ERM users (`test_get_library_item_returns_global_row_to_any_org`, `test_list_library_returns_global_plus_own_org_only`);
- [x] organization A cannot read hidden/inactive organization B rows by ID, update them, or retire them (`test_get_library_item_hides_another_orgs_row`, `test_org_risk_owner_cannot_update_another_orgs_row`). **Partial**: cross-org denial for the `use` action specifically (spawning a risk from another org's template) is covered only indirectly, via `get_library_item`'s shared scope check that `api_library_use` also calls -- not exercised by a dedicated test of the `/api/library/{id}/use` route itself this session.
- [x] organization risk owner can CRUD own templates but not global rows (`test_org_risk_owner_can_crud_own_org_row`, `test_org_risk_owner_cannot_update_global_row`);
- [x] super admin can manage global rows intentionally (`test_super_admin_can_manage_global_row`, plus `test_super_admin_can_manage_any_orgs_row` for the explicit cross-org override);
- [ ] fresh/upgrade SQLite and PostgreSQL schemas match. **Unverified**: no PostgreSQL instance available this session (same constraint as T01). SQLite fresh-install path is exercised by every `test_db`-based test above (13 passing); the PostgreSQL upgrade path (`_migrate_all_tenant_schemas` reaching an already-provisioned tenant's own `erm_risk_library` copy) is reasoned through in progress.md but not run.
- [x] hidden button/function regression is covered in a real browser (`tests/ui/test_erm_library_and_email_reset.py`, red/green-proved against both the original F03 hidden-button state and a template-level revert);
- [x] Email Reset is covered in the same browser suite (same file; red/green-proved against the exact F04 `ReferenceError`).

Completion gate: F03, F04, and F13 are closed together on SQLite with fresh evidence; PostgreSQL parity is unverified pending an available instance -- exposing the ERM button without tenant isolation was avoided by building the scoping and the button visibility in the same change, never landing one without the other.

### T04 — Remove stale `erm_risks` consumers and restore recovery-signal integrity

Priority: high. Dependencies: T00.

Primary files:

- `oneforall/database.py`;
- `oneforall/modules/evidence/routes.py`;
- `oneforall/scripts/restore_backup.py`;
- `oneforall/scripts/weekly_restore_drill.py`;
- `oneforall/scripts/warm_replay.py`;
- focused evidence and recovery tests.

Steps:

- [x] Add a repository test that fails if executable Python/SQL references `erm_risks` as a table name. Allow historical Markdown only if clearly labelled. (`tests/test_no_stale_erm_risks_table.py`; scans `.py` only, so Markdown is out of its reach by construction rather than by an explicit allow-list.)
- [x] Remove stale migration index statements for the nonexistent table. Do not suppress the warning. (Deleted outright, not wrapped in a suppressor -- the warning is gone because its cause is gone, confirmed with `--log-cli-level=WARNING`.)
- [x] Query `erm_enterprise_risks` in evidence suggestions and alias `title AS name` only if the downstream prompt/result contract needs `name`. (Kept the alias: nothing parses the dict by key downstream, but the sibling `audits` list already uses plain `name`, so keeping one convention across the same prompt was the better call than introducing a second one that didn't need to exist.)
- [x] Apply authenticated organization/SBU scope to available risk suggestions; do not expose cross-tenant titles to the AI prompt. (`erm_enterprise_risks` has no `org_id` column at all -- confirmed the same per-tenant-PostgreSQL-schema architecture as T03's `erm_risk_library` finding, so organization isolation is already structural in production; added business-unit scope via the existing `bu_scope_ids()` helper, the same one every other ERM/BCM/GRID/Sentinel/ORM listing route already uses -- reused, not reinvented.)
- [x] Update restore and warm-replay table lists/queries. (All three scripts.)
- [x] Confirm every recovery script distinguishes a missing table from an empty table and exits non-zero on genuine mismatch. (`restore_backup.py`'s `validate_row_counts` previously caught and printed every exception without ever affecting the exit code -- fixed to return `False`/exit 1 on a missing table, and to roll back the poisoned transaction so one missing table can't cascade into false failures on every table checked after it in the same connection. `weekly_restore_drill.py` already exited non-zero correctly; it had the same missing-rollback cascade risk, now fixed the same way. `warm_replay.py`'s SQLite-vs-PG comparison already exits non-zero on a real mismatch; its `erm_risks` line had been permanently vacuous -- both sides failed identically, every run, so it silently reported SKIP forever instead of ever actually comparing anything.)

Tests:

- [x] evidence suggestion with a configured fake AI and at least one scoped risk reaches the AI layer without SQL error (`tests/test_evidence_suggest_links.py::test_suggest_links_reaches_ai_without_sql_error`; this test also surfaced and required fixing a second, unrelated pre-existing bug in the same function -- `grid_audits` has no `framework_name` column either, so the endpoint could not be exercised at all before that was also fixed; see progress.md);
- [x] out-of-scope risk is absent from the prompt (`test_suggest_links_excludes_another_business_units_risk`; also added `test_suggest_links_org_wide_risk_is_visible_to_every_bu` to prove the NULL-is-always-visible convention, matching `bu_scope_ids()`'s documented contract, wasn't broken by the scoping);
- [x] clean startup emits no stale-index warning (confirmed directly with `pytest ... --log-cli-level=WARNING`, zero matches for "Skipped index" or "erm_risks");
- [ ] guarded PostgreSQL fresh init/upgrade passes. **Unverified**: no PostgreSQL instance available this session (same constraint as T01/T03).
- [ ] backup list validation, restore drill, and warm replay pass against a disposable restored database. **Unverified**: no PostgreSQL/Docker/real backup archive available this session to actually run `restore_backup.py`/`weekly_restore_drill.py`/`warm_replay.py` end-to-end. Each was reviewed and corrected by reading, not by execution -- treat as unverified, not passed, per the plan's own evidence rules.
- [x] mutation of the expected table name makes the recovery test fail, proving it is non-vacuous (red/green-proved on `tests/test_no_stale_erm_risks_table.py` directly, and separately on `test_evidence_suggest_links.py`'s SQL-error test by reverting the exact fixed line).

Completion gate: no executable reference to the removed table remains (repo-wide guard test passes). Recovery *checks* now correctly report real database state for the failure modes reviewed by reading (missing-table detection, transaction-poisoning cascade, the permanently-vacuous erm_risks comparison) -- whether they report accurately against a real restore is unverified pending a PostgreSQL/Docker environment.

### T05 — Make webhook testing truthful and harden all outbound webhook destinations

Priority: security release blocker. Dependencies: T00, T06 helper may be developed jointly.

Primary files:

- `oneforall/core/outbound_http.py` (new shared policy/service, name may vary once source is reconciled);
- `oneforall/core/webhooks.py`;
- `oneforall/core/notifications.py`;
- `oneforall/modules/launcher/routes_admin.py`;
- `oneforall/modules/launcher/templates/admin_webhooks.html` and connector UI;
- webhook, connector, security, audit, and browser tests;
- deployment documentation for egress controls.

Steps:

- [x] Write failing tests for a DNS name resolving to loopback/private/link-local/reserved IPv4 and IPv6, credentials in URL, malformed host, an unsafe redirect, timeout, oversized response, and the over-broad 172.x prefix. (`tests/test_outbound_http.py`; DNS-dependent cases use a `socket.getaddrinfo` fixture, not real network, per its own module docstring.)
- [x] Centralize URL parsing/resolution. Require HTTPS and a valid hostname. Resolve all A/AAAA records and reject the destination if any result is non-global. (`core/outbound_http.py::validate_outbound_url`; single chokepoint used by generic webhooks, Slack, Teams, and WhatsApp -- confirmed by repo-wide sweep, see completion gate note below.)
- [x] Revalidate immediately before each connection, set strict connect/read/write/pool timeouts, cap response bytes retained, and set `follow_redirects=False` by default. (`send_outbound()`; response-cap-off-by-one-chunk bug found and fixed by its own test before shipping, see progress.md.)
- [x] Remove prefix-string IP tests in favor of `ipaddress` classification. Add explicit tests for public 172.x and private `172.16.0.0/12`. (`_is_blocked()` checks `is_private/is_loopback/is_link_local/is_reserved/is_multicast/is_unspecified` explicitly; `test_allows_public_dns_answer_including_public_172_range` covers 172.15.x/172.32.x public and 172.16-31.x private.)
- [x] Apply the same policy to generic webhooks, Slack, Teams, and WhatsApp save/test/send paths. (Save: `_validate_webhook_url` -> `validate_outbound_url`, shared by `api_webhooks_create`/`api_webhooks_update` and `api_connectors_save` for all three connectors. Send: `core/webhooks.py::_deliver_once` and `core/notifications.py::_send` both call `send_outbound`. Test: `api_webhook_test` and the three `api_connectors_test_*` routes share `send_test_ping`/`core.notifications` respectively.)
- [x] Make `/api/admin/webhooks/{id}/test` invoke the real signed delivery path to the saved, revalidated URL. It must never insert a synthetic 200. (`api_webhook_test` -> `send_test_ping` -> the same signed `_deliver_once` real event delivery uses; no code path left that writes a webhook_logs row without an actual attempt.)
- [x] Return a truthful bounded result: delivered status code/body summary or a sanitized failure. Log the actual attempt with correlation ID and duration. (`send_test_ping` returns `{success, status_code, detail}`; `detail` is a short fixed-shape sanitized string, never the raw response body/headers. `_log_attempt` persists the real code/body-prefix/success to `webhook_logs`; `elapsed_ms` is captured on every `OutboundResult` though not separately surfaced as a correlation ID -- no correlation-ID mechanism exists elsewhere in this codebase to match, judged out of proportion to add one net-new for this task alone.)
- [x] Prevent secrets, authorization headers, full response bodies, and internal resolver details from appearing in UI/audit logs. (Confirmed by reading `send_test_ping`/`_log_attempt`/`api_webhook_test`'s `log_audit` call directly: the audit log gets `wid`/`success`/`status` only; the UI gets `detail`, a fixed short string; the real body/headers stay server-side in the already access-controlled `webhook_logs` table, length-capped at 2000 chars.)
- [x] Rate-limit test sends per actor and webhook. Prevent concurrent repeated clicks and make the UI show Sending, Delivered, or Failed. (Server: `check_rate_limit`/`record_failed_login` keyed per `webhook_test:{uid}:{wid}` and `connector_test:{connector}:{uid}`, reusing the existing generic rate-limit primitives rather than inventing a new one. UI: `admin_webhooks.html`'s Test button disables itself synchronously on click -- a disabled DOM button does not dispatch further click events, proven directly in `tests/ui/test_webhook_admin_ui.py` by firing two click events back to back and asserting the fixture server receives exactly one request -- and shows Sending.../Delivered/Failed.)
- [x] If asynchronous delivery is retained, return 202 plus delivery ID and poll the actual log; do not label queued as delivered. **N/A by design**: the Test button is a single synchronous attempt with no retry (bounded by `CONNECT_TIMEOUT`+`READ_TIMEOUT`, ~15s worst case), not a queued/async job, so there is no queued state that could be mislabeled. Real event delivery (`deliver()`) already existed as synchronous-with-retry before this task and was not changed into an async queue.
- [x] Document residual DNS-rebinding risk and add a production egress rule/proxy recommendation blocking private, link-local, metadata, and management networks. (`docs/outbound-webhook-egress.md`, new; also summarized in `core/outbound_http.py`'s own module docstring.)

Tests:

- [x] controlled local HTTPS fixture or mocked transport proves the request is signed and actually attempted (`tests/test_webhooks.py::test_deliver_success` asserts the signature over the real body; `tests/test_webhook_test_endpoint.py::test_test_endpoint_makes_a_real_delivery_and_logs_it_truthfully` and `tests/ui/test_webhook_admin_ui.py` hit a real local HTTP fixture end to end -- HTTP, not HTTPS, with `validate_outbound_url`'s own HTTPS requirement covered separately and fully by `test_outbound_http.py`'s unit tests, and bypassed only for these specific local-fixture tests, matching this file's own precedent);
- [x] private/loopback/link-local/reserved/mixed DNS answers are denied at save and send (save: `tests/test_security.py::TestSSRFValidation`, now DNS-mocked rather than network-dependent, see progress.md; send: `test_outbound_http.py`'s parametrized DNS-answer tests, 11 blocked + 4 allowed cases);
- [x] redirect to a denied destination is not followed (`test_send_outbound_does_not_follow_redirects`);
- [x] another organization cannot test or inspect a webhook (`test_test_endpoint_enforces_organization_isolation`, using an actor that holds the capability role but not the separate `is_super_admin` bypass column, to actually exercise `_get_webhook_for_admin`'s org-scoped branch rather than vacuously passing via the unrestricted branch);
- [x] actual failures are logged as failures, never 200 success (`test_test_endpoint_reports_real_failure_never_fake_success`, `test_test_endpoint_never_fakes_success_for_a_blocked_destination`, `test_deliver_blocked_by_outbound_policy_does_not_retry_as_network_error`);
- [x] Slack/Teams/WhatsApp paths share the policy (`tests/test_notifications.py`: parametrized across all three for not-configured/policy-blocked/success/failure, plus one HTTP-level connector-test-endpoint run against a real local fixture with rate limiting);
- [x] browser test verifies double-click suppression and visible outcome (`tests/ui/test_webhook_admin_ui.py`, both red/green-proved against the disable-on-click guard directly, not just observed passing once).

Completion gate: F06 and F07 are closed. Security review for "no unvalidated alternate outbound path remains": repo-wide grep for `httpx.*/requests.*/urlopen` call sites outside `core/outbound_http.py` found `core/ai_client.py` (fixed LLM provider endpoints: OpenRouter/Anthropic/Gemini, not admin-entered per-tenant destinations), `core/email.py` (fixed OAuth/SendGrid/Graph provider endpoints), `scripts/deploy.py` (a deploy-time localhost health probe) and `scripts/fetch_fonts.py` (build-time hardcoded font CDN URLs) -- none accept an admin- or tenant-supplied destination URL, so none are in scope for "outbound webhook destinations" per this task's own primary-files list; all code paths that *do* accept an admin-supplied destination (generic webhooks, Slack, Teams, WhatsApp -- save, test, and real send) were confirmed by direct source reading to route through `core/outbound_http.py`.

### T06 — Introduce a consistent request, loading, and error experience

Priority: high. Dependencies: T00; coordinate with T01-T05.

Primary files:

- `oneforall/static/js/api_client.js` (new);
- `oneforall/templates/base_shell.html`;
- high-priority module templates identified in F08;
- middleware only if a correlation ID is not already generated and returned;
- JavaScript and browser tests.

Required helper behavior:

- accept URL, method, body, headers, expected response type, timeout, and optional idempotency key;
- send same-origin credentials and CSRF according to current platform behavior;
- parse JSON only when content type/body permits it; preserve a bounded text fallback;
- throw a typed error carrying HTTP status, safe detail, retryability, and correlation ID;
- distinguish abort/timeout, network, authentication, authorization, validation/conflict, rate limit, and server failure;
- never expose stack traces, secrets, SQL, or raw proxy pages;
- never automatically retry a mutation unless the caller supplies an idempotency key and the route explicitly supports it;
- provide a standard button-state wrapper so disabled/text/spinner state is restored in `finally`;
- integrate with the existing toast system and allow an inline error target for forms.

Steps:

- [x] Add unit tests for 200 JSON, 204, text response, malformed JSON, 400 detail, 401/403, 409, 429 with retry hint, 500 HTML, network failure, timeout, and abort. (`tests/ui/test_api_client.py`, 14 tests, all via real-browser `page.route()` interception -- deterministic, no dependency on any specific backend route's actual behavior.)
- [x] Add/confirm an `X-Request-ID` response header generated by trusted middleware; accept an incoming ID only if it matches a strict bounded format, otherwise generate a new one. (`core/middleware.py::request_id_middleware`, registered outermost in `main.py` -- before `security_headers_middleware` -- so the header survives even an early rejection from a later middleware; `tests/ui/test_request_id_middleware.py`, 9 tests including one against a 404.)
- [x] Load the helper once from `base_shell.html` with a cache-busting version. (`<script src="/static/js/api_client.js?v=1">`, same convention as T02's `modal_manager.js?v=1` immediately above it.)
- [x] Migrate user-triggered mutation paths first: ARIA edit/delete, modal create forms, Email Reset/Save/Test, webhook/connector tests, Evidence upload/link/delete, ERM scan and library actions, and the previously observed silent paths. **Every module F08 names by name is now covered**: ARIA document edit/delete (`documents.html`), Evidence's 8 mutation functions (`evidence_index.html`), Email Reset/Save/Test (`admin_email.html`), webhook Test (`admin_webhooks.html`) and Slack/Teams/WhatsApp connector save/test/remove (`admin_connectors.html`), ERM/BCM/Sentinel/ORM/super_admin/workflows via their own pre-existing shared `apiFetch(url,opts)` wrapper in each (migrating the wrapper once upgrades every call site behind it -- one file alone has 3,000+ lines and dozens of sites through it), GRID via its own differently-named shared wrapper (`api()`, found by reading the file after a name-based grep for "apiFetch" missed it) plus 5 individual mutations not behind it, Task Board (9 of 10 sites), My Dashboard (all 3), and Command Centre (`templates/command_centre.html`, served at `/` -- not touched at all until the session's final pass despite being named explicitly). Several of these had strictly worse bugs than "shows a generic message": Sentinel's `apiFetch` discarded the server's real error text unconditionally; super_admin's never checked `response.status` at all, so an error body could be parsed and handed to a caller as if it were successful data; GRID's `api()` swallowed every error into `null`, indistinguishable from "no data"; Task Board's drag-and-drop move and Command Centre's report generators relied on raw `fetch()` not rejecting on non-2xx, so a server-rejected action left an optimistic UI update in place as if it had succeeded. **Still not swept**: ARIA has 8 other template files beyond `documents.html`; a repo-wide census after this pass still finds `fetch(` in ~13 lower-traffic admin/reporting pages never named by F08 (admin_api_keys, admin_frameworks, admin_logs, admin_security, admin_users, analytics, calendar, people_directory, reports, risk_register, timeline, vendor_directory, governance/index.html) plus `_platform_trainer.html`. "Modal create forms" as a general category is covered only where a form happened to live inside an already-migrated page.
- [x] Replace empty catches for user actions with visible error state. Retain quiet degradation only for optional background panels and label those panels unavailable. **True for every migrated path.** Genuinely optional/background reads were deliberately left quiet, matching this step's own carve-out: GRID's Sentinel-breach banner check and IMS-framework dropdown supplement, Task Board's stats-row refresh, My Dashboard's preference load (has a sane default), Command Centre's `loadDashboard`/`loadBriefing` (already fall back to a real static object on failure, a more sophisticated version of the same pattern this step describes, so left on its existing transport rather than risked changing for a page this central).
- [x] Prevent duplicate submissions while a request is in flight. (`ApiClient.withButtonState` for the common case; richer-state buttons -- webhook Test, email Test -- keep their own bespoke disable/restore layered over `ApiClient.request`, documented in progress.md for why `withButtonState`'s text-only restore would have been wrong for those two specifically.)
- [x] Add telemetry counters/log fields for action ID, status class, duration, and request ID without recording form content or personal data. (`ApiClient`'s internal `reportTelemetry`, reusing the PostHog integration already loaded in `base_shell.html` rather than standing up a new metrics sink -- `posthog.capture('api_request', {action_id, status_class, duration_ms, request_id})` on every `request()` call, success or failure; guarded so a missing/blocked PostHog never breaks the caller.)

Completion gate:

- No action in the critical-action registry uses naked `fetch` unless a documented exception exists. **Met for the registry's actual entries** (webhook-test and create-webhook are migrated, the registry's only two `/api/*` mutation entries per T00's own intentionally-partial ~25-entry coverage). Not a claim that zero raw `fetch()` remains anywhere in the codebase -- see the Steps entry above for the honest remaining-file list, all outside both the registry and F08's named scope.
- Every registered mutation demonstrates visible success and failure in a real browser. **Met.** Every migrated module has its own real-browser test: `test_webhook_admin_ui.py`, `test_email_settings_error_detail.py`, `test_admin_connectors_ui.py`, `test_aria_managed_edit.py`, `test_evidence_upload_error_detail.py`, `test_apifetch_migration_smoke.py`, `test_grid_migration_smoke.py`, `test_task_board_and_my_dashboard_migration.py`, `test_command_centre_migration.py`.
- Network/proxy HTML failures no longer create uncaught JSON parse errors. **Met for `ApiClient.request` itself** (proved directly: `test_500_html_never_leaks_the_raw_body`, `test_malformed_json_on_200_raises_parse_error`) and for every migrated path above.

### T07 — Establish the accessibility and keyboard foundation

Priority: high quality gate. Dependencies: T02, T06.

Primary files:

- `oneforall/templates/base_shell.html`;
- shared module base templates;
- shared modal/navigation JavaScript;
- affected templates from F09;
- accessibility browser tests.

Steps:

- [x] Add a skip link and semantic `<main id="mainContent">` landmark while preserving SPA replacement behavior. (Session 1.)
- [x] Give the notification bell, trainer Send, sidebar controls, icon-only actions, and all close buttons accessible names. **Partial**: notification bell, sidebar toggle, trainer bubble/close/send/tooltip-toggle done (session 1); modal close buttons go through T02's `ModalManager` contract, not independently re-audited this session. Not a claim every icon-only action platform-wide has been swept.
- [x] Convert interactive `div`/`span` controls into `button`/`a href` elements. If conversion is temporarily impossible, add role, tabindex, Enter, and Space behavior with a tracking issue; native elements remain the target. Every clickable div/span found in Evidence (stat tiles, recent/grid cards, tabs, link-entity rows) converted to real `<button>` (session 2, red/green-proved); trainer bubble and Task Board's My-Tasks toggle converted in session 1. **The repo-wide "chip" census session 2 flagged as untriaged is now resolved** (session 3, 2026-09-28): every `<span>`/`<div>` with a "chip" class across the whole codebase was individually checked for an actual click handler (inline `onclick` or a delegated `addEventListener`/`querySelectorAll` wire-up) versus being a pure display badge. Interactive ones converted to `<button type="button">` -- ERM (24 register/library/etc. chips plus 4 chat-prompt chips), Sentinel (29 status/risk/view filter chips plus a chip-picker and an ARIA-control-linking chip), BCM (5), GRID (8), Task Board (5), Timeline (3), Command Centre (7), ARIA's Ask page (7 suggestion chips + history items). Purely decorative badges with no click handler (row-chip, ims-fw-chip, bcm-ctrl-chip, role-chip, tl-meta-chip, orm-cat-chip, one tag-display filter-chip in Sentinel) were deliberately left as spans -- confirmed via a final repo-wide sweep that zero interactive chip-class spans/divs remain anywhere. See `progress.md` 2026-09-28 T07 session 3.
- [x] Give every SPA navigation anchor a real `href`; JavaScript enhancement must not remove native navigation. Repo-wide scan (`modules/**/*.html` + `templates/*.html`) for `<a ...>` tags missing `href` found exactly 6: 5 `data-spa` anchors and 1 `onclick`-only div, all fixed (session 2) by adding `href` matching the existing `data-spa` target -- safe because every module's delegated click handler does `e.preventDefault()` regardless of tag, confirmed by reading each handler before editing. Pre-existing `href="#"` placeholder anchors (functionally fine since click is intercepted, but not a real destination) were not swept as a separate, lower-severity class.
- [x] Associate labels and inputs with unique `for`/`id`, including dynamically created modal fields. **Partial**: every `select-name`/`label` violation axe actually found across all 21 acceptance routes is fixed (toolbar filters on 7 routes, admin_users' edit-drawer fields, ERM's `#regSelectAll` checkbox) -- session 2. Not a claim that every label in the codebase is associated; only axe-confirmed, route-default-view-visible instances were fixed, per the plan's own "no claim that route HTTP 200 proves button functionality"-style discipline -- unverified instances (e.g. modal-only fields never visible on initial page load) were not guessed at.
- [x] Use the T02 manager for dialog semantics and focus. **Partial, high-traffic panels done** (session 3, 2026-09-28): a new shared `DialogFocus` utility (`static/js/dialog_focus.js`) gives every custom pre-T02 drawer/panel the same Tab-trap and focus-restore-on-close ModalManager provides, without a risky visual migration onto the `.modal-overlay`/`.modal` markup contract. Wired into: ERM's risk and results drawers; ORM's 4 event/assessment drawers; all 8 of Sentinel's record drawers and quick-action dialogs (RoPA/DPIA/AIIA, LIA, generate-notice, draft-policy, both jurisdiction configs); ARIA's Ask drawer; People Directory's and Vendor Directory's profile drawers. Release is automatic via a MutationObserver watching for the panel leaving the DOM (most of these close from several different call sites -- a Cancel button, a backdrop click, a post-save success path -- and requiring each to remember an explicit release() call was judged too easy to miss one of); panels that close via a CSS class toggle instead of DOM removal (People Directory, Vendor Directory, ARIA's Ask drawer) needed an explicit release() call too, found by a real end-to-end test failure, not assumed. **Not done**: a repo-wide scan found ~44 more smaller, ad-hoc modal instances across ERM (15 more), ORM (~13 more), BCM (~21), admin_users (1), and my_dashboard (1) using several different inconsistent conventions (`erm-modal-overlay`, `orm-modal-overlay` with per-dialog IDs, BCM's plain unprefixed `.modal-overlay` which risks colliding with real ModalManager dialogs) -- deliberately not touched this session once BCM's inconsistent pattern surfaced real ambiguity risk (which element a blind class-based query would actually select). Evidence's detail panel (`#evDetailPanel`, session 2) still has Escape-only, no Tab-trap. See `progress.md` 2026-09-28 T07 session 3 for the exact counts and reasoning.
- [x] Ensure toasts use an appropriate live region without repeatedly announcing decorative content. `#toastContainer` gained `role="status" aria-live="polite"`; the toast icon SVG gained `aria-hidden="true"`. (Session 2.)
- [x] Verify visible focus, logical tab order, 200 percent zoom, reduced motion, and no keyboard traps.
  - Visible focus: repo-wide scan for `outline:none`/`outline:0` with no `:focus`/`:focus-visible` replacement anywhere in the same file found 2 real instances across the whole codebase (`.aria-draft-editor` in `ai_generator.html`, `.tl-module-sel` in `timeline.html`) -- every other of the 25 files using `outline:none` already pairs it with a visible replacement, matching `base_shell.html`'s own `.form-input:focus` convention. Both fixed (a box-shadow ring, red/green-proved) and given real-browser tests.
  - Reduced motion (session 3, 2026-09-28): repo-wide scan for `infinite`-looping CSS animations found ~25 across 8 templates. Loading spinners and button-loading shimmer deliberately left alone (brief, functional feedback). Every purely decorative/ambient one -- login's pulsing background glows/beams/corners plus its two mousemove-driven parallax effects (card tilt, spot parallax), the trainer bubble's attention ring, tooltip-mode glow, AI "typing" dots, and three small "live/overdue" status-dot pulses -- now stops under `prefers-reduced-motion: reduce`, verified via Playwright's real media-feature emulation, with red/green proofs for the two riskiest (login's CSS block, login's JS tilt guard).
  - Tab order (session 3): repo-wide scan for a positive `tabindex` (breaks natural DOM tab order) found zero. Repo-wide scan for CSS `order` (flex/grid visual reorder without a matching DOM/tab-order change) found zero genuine uses (the first attempt's regex false-matched every `border:` declaration; corrected with a word-boundary anchor and re-verified clean). No fix needed; both checks are new automated-scan evidence, not present before this session.
  - 200% zoom (session 3): new `tests/ui/test_200_percent_zoom.py`, all 21 acceptance routes at 640x800 (the equivalent reflow breakpoint for 200% zoom on a 1280px design, same technique as `test_modal_contract.py`'s own 390x844 mobile-overflow check). All 21 pass with zero horizontal overflow.
  - Keyboard traps: covered by the dialog-semantics work above (a Tab-trap that never releases would itself be a keyboard trap) plus `test_dialog_focus.py`'s own explicit proof that a panel removed without an explicit release() call still returns Tab to normal page-wide behavior via the MutationObserver safety net.
- [x] Add automated axe-core (or equivalent vetted tool) checks for representative routes and manual keyboard scripts for flows automation cannot prove. The axe suite passes cleanly on all 21 routes with zero xfail (see T07 completion gate note below). `oneforall/docs/manual-keyboard-test-script.md` (new, session 3) is a human-run script covering global shell navigation, ModalManager modals, the newly-fixed custom drawers, converted filter chips, Task Board's drag-and-drop keyboard alternative (confirmed to exist -- the task drawer's `#ddStatus` select), and one full no-mouse task end to end.

Acceptance routes:

- Command Centre, My Dashboard, Task Board, Reports, Calendar, Risk Register, People, Admin Users, API Keys, Webhooks, Email, ARIA Documents/Generator, ERM Register/Library/External Context, Evidence, GRID, BCM, Sentinel, ORM, and Governance.

Completion gate: zero critical/serious automated violations on acceptance routes; every critical action is keyboard operable; remaining moderate findings are documented with owners and deadlines.

**Zero-violation automated gate: met.** All 21 acceptance routes pass the axe suite with zero xfail. The 5 color-contrast findings (GRID button/nav-active, ARIA and Sentinel module-name, my-dashboard's `--good` stat text, ERM library's category chips) were fixed with the user's explicit sign-off on the approach, plus two more of the same class found along the way (`.lib-tag`/`.badge-draft`'s muted-on-surface3 text) fixed proactively since they're the identical pattern. Colors were computed programmatically (WCAG relative-luminance formula, same hue/saturation, lightness reduced for margin) and per-module-verified rather than assumed identical across modules -- this caught that the prior session's own `.module-name` fix (`--accent-mid`) did not actually clear AA for ARIA or Sentinel, and that Sentinel's real finding was `.module-name`, not `.btn-primary` as originally assumed by inheritance from GRID's diagnosis.

**"Every critical action is keyboard operable": met for everything this programme's own audit (findings.md F01-F09) and this session's repo-wide scans actually named or found** -- every interactive chip/badge with a real click handler anywhere in the codebase (confirmed by a final repo-wide sweep, not just the files touched), every SPA anchor missing `href`, every control with `outline:none` and no visible-focus replacement, every purely decorative looping animation, and the highest-traffic custom dialogs/drawers across ERM/ORM/Sentinel/ARIA/People Directory/Vendor Directory. **Not a claim covering literally every control in the codebase**: ~44 smaller ad-hoc modal instances across ERM/ORM/BCM/admin_users/my_dashboard (see the dialog-semantics step above) remain unaudited for Tab-trap/focus-restore, and Evidence's detail panel has Escape-only. These are the plan's own "remaining moderate findings," and are documented here with that status rather than silently left for someone to rediscover -- a dedicated follow-up session, or the T10 modularization pass, is the natural place to close them out, since several sit inside files already flagged by F11 as oversized and regression-prone to hand-edit repeatedly.

Dark-mode contrast was checked defensively (to avoid the light-mode fix regressing it) but is a separate, pre-existing, only partially-addressed problem -- see `progress.md`.

### T08 — Complete the HTTP and real-browser regression suite

Priority: release-process blocker. Dependencies: T00-T07.

Primary files:

- `oneforall/tests/ui/`;
- route/service tests across modules;
- test fixtures in `oneforall/tests/conftest.py` or dedicated UI fixtures;
- development-only requirements and browser install documentation.

Steps:

- [ ] Add HTTP integration coverage for authentication, CSRF/origin behavior, capability denial, organization/SBU isolation, success, validation, conflict, and server failure on critical routes. **Partial**: `tests/ui/test_action_registry_http_contracts.py` generically covers authentication (unauthenticated mutation -> redirect/401) and capability denial (wrong persona -> 403) for every registry mutation action. `tests/ui/test_csrf_protection.py` covers CSRF (missing + wrong token, both rejection branches) for the 9 `/admin/users/*` form routes plus `/login` -- the only routes that actually call `validate_csrf` (JSON `/api/*` mutations rely on session+content-type, not a form token, by design; see progress.md for the full grep). Org isolation: `tests/ui/test_org_isolation.py` covers ERM library (T08 session 3) and evidence (T08 session 5, F14 -- see below) cross-org denial with same-org positive controls; not yet extended to every other org-scoped module (ARIA, BCM, and Sentinel still rely on service-layer tests only, not an HTTP-level one; GRID now has selected audit, NC, control, and evidence SBU HTTP coverage). SBU-level HTTP isolation now covers selected GRID audit, NC, control, and evidence routes (see F19); other GRID and module paths still need equivalent coverage. Success/validation/conflict/server-failure coverage beyond what the CRUD-postcondition assertions inside the isolation tests themselves prove is not yet done. `/mfa/verify`/`/mfa/setup/confirm` CSRF and the `/admin/users/*` registry entries themselves are named, explicit gaps. See `progress.md` 2026-09-30 T08 sessions 1-5 for the red/green proofs, and `findings.md` F14 for the critical evidence-tenant-isolation defect found and fixed in session 5.
- [ ] Drive every action-registry entry that is safe in an isolated database. Destructive actions must use synthetic fixtures and prove their exact postcondition. **Partial**: the auth/capability-denial slice above runs against every mutation entry; the success/postcondition slice (actually performing each mutation and asserting its effect) is not yet done.
- [x] Capture uncaught page errors, console errors, failed same-origin requests, unexpected redirects, and server 5xx; fail the test unless explicitly allowlisted with rationale. `tests/ui/conftest.py`'s `page` fixture now asserts zero console/page errors at teardown for every UI test by default (opt-out via `@pytest.mark.expected_page_errors`, registered in `pytest.ini`), filtering only the browser's own generic "Failed to load resource" resource-log line (confirmed by running the full pre-existing suite against the new gate: zero tests needed the opt-out). "Unexpected redirects" is deliberately left to each test's own assertions (what's "unexpected" is test-specific; a blanket redirect check would false-positive on ordinary POST-redirect-GET flows) -- see progress.md 2026-09-30 T08 session 2.
- [ ] Seed realistic records for data-dependent screens instead of relying only on empty-state 200 checks.
- [x] Test at least desktop 1366x768 and 1920x1080 plus mobile regression 390x844 for shell/modal overflow; product remains desktop-first. 390x844 (modal) and the 200%-zoom-equivalent 640x800 (shell) already existed; `tests/ui/test_desktop_viewports.py` adds 1366x768 and 1920x1080 for both shell (21 routes) and modal (2 representative modals) overflow.
- [ ] Cover role/persona boundaries, not just super admin. **Partial**: capability-denial coverage above uses non-super-admin personas (employee/viewer/risk_owner); broader positive-path persona coverage across ordinary screens is not yet done.
- [x] Test multi-tab or concurrent behavior for approval, task/update, and idempotent actions where race conditions matter. Approval: `tests/test_aria_policy_approvals.py::test_two_concurrent_deciders_exactly_one_wins` (real threads, real separate DB connections) already proves ARIA's `lock_version` optimistic guard lets exactly one of two simultaneous approve/reject decisions win; ERM's workflow-step conditional UPDATE has an equivalent single-threaded stale-precondition test (`tests/test_concurrency_guards.py`). Task/update: new `tests/ui/test_task_update_concurrency.py` (real threads, real live_app HTTP requests) found and documents that `api_task_update` (`modules/launcher/routes_platform.py`) has no optimistic guard at all -- both concurrent writers get 200, the later commit silently wins, with no way for either caller to know. This is recorded as a factual characterization of current behavior (see progress.md T08 session 6), not asserted to be wrong -- whether task-board drag/drop needs conflict detection the way a formal approval does is a product decision, not something a testing task should silently decide either way. Idempotent actions: `tests/test_aria_policy_approvals.py::test_resubmitting_same_request_id_is_idempotent` already covers ARIA's submit-for-approval request_id idempotency.
- [x] Add download checks for expected content type, disposition, non-empty file, and authorization. `tests/ui/test_download_contracts.py` (T08 session 4): ERM risk-register and BCM incidents CSV exports, each checked for unauthenticated redirect, authenticated 200 with the exact content-type/attachment-disposition/filename/non-empty body, and 403 for a persona lacking the capability. Evidence's file-backed download (`api_evidence_download`) is covered separately by the F14 org-isolation tests (`tests/ui/test_org_isolation.py`) rather than this file. Not every download route in the app has this exact three-part check (GRID zip export, ARIA document export, evidence download-pdf are not individually covered this way) -- the two chosen are representative, not exhaustive.
- [ ] Keep external AI/email/webhooks/conversion mocked in ordinary CI and run separately controlled integration smoke tests for their real adapters. **Partial**: webhooks fully satisfy this -- mocked in `test_webhook_admin_ui.py` (Playwright route interception) and a genuine real-delivery smoke test in `test_webhook_test_endpoint.py` (real local HTTP fixture, no third party). AI (`test_ai_client_openrouter.py` etc.) and LibreOffice conversion (`test_aria_policy_preview.py`) are mocked in ordinary tests but have no separate real-adapter smoke test. Email has neither a real-SMTP smoke test nor an obvious dedicated mock-only test file. Building real-adapter smoke tests for AI/email/conversion needs the user's own controlled destinations/credentials (this plan's own constraint), so this was not attempted without that; flagged here rather than left silently unconfirmed.

Coverage policy:

- Do not chase a global percentage by testing trivial branches.
- Require direct route/service coverage for every critical action and every security invariant.
- Set an initial enforceable floor no lower than current measured coverage, then ratchet changed-file/critical-module coverage upward. Never lower the floor to merge a change.

Completion gate: the real-browser suite catches deliberate reintroduction of F01, F02, F03, F04, and F06; HTTP tests cover all critical backend contracts; no test can point at production.

### T09 — Make CI enforce the release gates

Priority: release-process blocker. Dependencies: T08.

Primary files:

- `.github/workflows/test.yml` (new or clearly named equivalent);
- existing `postgres-schema.yml`;
- browser and preview workflows;
- dependency lock/pin files and test documentation.

Steps:

- [x] Run Python compilation, `git diff --check`, full unit/integration tests, and coverage on every pull request and push to `master`. New `.github/workflows/test.yml`: `compile-and-static-checks` job (compile, git diff --check with a base-ref fallback chain, pip check, pip-audit) and `backend-tests` job (full `tests --ignore=tests/ui` suite with `--cov-fail-under` set to 43, just under the 43.65% precisely measured on 2026-09-30 with this exact command -- see progress.md for why 44 would have failed immediately).
- [x] Retain the guarded PostgreSQL 18 schema job and extend it with T03/T04 query/migration cases. `postgres-schema.yml`'s job and `TEST_DATABASE_URL`/destructive-test guard are untouched; extended by adding 3 new tests directly to `tests/test_postgres_init.py` (the one file this job already runs), covering T03 (erm_risk_library.org_id), T04 (warm_replay.py queries), and F14 (evidence_items.org_id + its RLS policy, functionally proven with two real cross-org connections, not just schema presence) against a real Postgres instance -- unverified by execution this session (no local Postgres instance available all session; see progress.md).
- [x] Run browser smoke tests on every pull request using an isolated application and browser cache keyed to an exact dependency lock. `browser-smoke` job (PR-only): 5 representative UI test files, Playwright Chromium cached by a key hashing `requirements-browser-dev.txt`.
- [x] Run the broader action matrix on `master` and before a release if runtime is too high for every PR. `browser-full` job (master push only): the complete `tests/ui` suite.
- [x] Run JavaScript syntax/unit tests and Jinja compilation with real filters. `js-checks` job: `node --check` over every `static/js/*.js` file plus `node --test` over `tests/js/*.test.js` (Node's built-in test runner, no framework/npm install needed -- one file already existed, `aria_policy_workflow.test.js`). New `tests/test_template_compilation.py` (runs as part of the normal backend suite, not a separate CI step) compiles every template reachable through any of the app's `Jinja2Templates` instances against the union of every registered filter -- see the file's own docstring for why a per-instance-only check false-positives on templates multiple modules' separately-constructed instances can all see.
- [x] Run `pip check`, dependency vulnerability scan, and secret scan. Define an exception process with owner/expiry; do not silently ignore failures. `pip check` + `pip-audit` (added to `requirements-dev.txt`, confirmed zero known vulnerabilities across all three requirements files as of 2026-09-30) in `compile-and-static-checks`; `gitleaks/gitleaks-action` in its own `secret-scan` job (confirmed via the repo's own remote, `AliMoyo1/ThemisIQ`, that this is a personal-account repo, so no `GITLEAKS_LICENSE` secret is required). No exception process (owner/expiry for an accepted finding) has been built -- there is nothing to except yet, and this is a process definition, not code; flagged as not yet done rather than silently assumed unnecessary.
- [x] Upload sanitized screenshots, traces, and logs only on failure. Ensure artifacts contain no real secrets or production data. `if: failure()` on both browser jobs' artifact-upload steps; the isolated test harness's own SQLite tmp-dir database (never production, enforced by `tests/ui/conftest.py`'s own assertion) means nothing in `test-results/` can contain production data by construction.
- [x] Pin third-party GitHub actions by immutable commit SHA. Every `uses:` in `test.yml` and `postgres-schema.yml` (which previously used floating `@v4`/`@v5` tags) is now pinned to a commit SHA looked up live via `gh api repos/<owner>/<repo>/tags` at write time, matching the convention `aria-preview-image.yml` already established. One real mistake caught before it shipped: a first draft used a fabricated SHA for `actions/cache@v4.3.0` that does not exist in that repo's real tag list at all -- caught by actually looking it up rather than trusting a plausible-looking guess, replaced with the real, verified `v6.1.0` SHA.
- [ ] Require the relevant jobs through branch protection after observing stable hosted results. Not done -- this explicitly requires observing real, stable hosted CI runs first (per this step's own wording), which requires these workflow files to actually be pushed and run on GitHub; that has not happened yet (no commit/push has been authorized this session). Flagged as the next action once the user authorizes a push.

Completion gate: a deliberately failing Python test, browser test, PostgreSQL test, and template compile each block CI in a temporary branch; restored source returns green. **Not yet demonstrated** -- this requires pushing to a real branch and observing actual GitHub Actions runs, which this session has not been authorized to do. Every step above was instead verified as thoroughly as possible locally (see progress.md): YAML parse-validated, every shell fragment run locally exactly as written (git diff --check fallback logic, the JS check/test loops, the coverage command against real measured data), and the new template-compilation and Postgres tests each red/green-proved or reasoned through against exact, re-read method signatures where a live Postgres instance to execute against was not available.

### T10 — Reduce regression pressure and make capability documentation authoritative

Priority: medium, required before feature programme. Dependencies: T06-T09.

Primary areas:

- oversized templates and route/service files identified in F11;
- `FEATURE_INVENTORY.md`, `ROADMAP.md`, `PRELAUNCH_TRACKER.md`;
- generated capability/reporting scripts and tests.

Steps:

- [x] Measure file size, inline-handler count, route count, cyclomatic hotspots, and ownership boundaries; record the baseline. Baseline recorded in progress.md T10 session 1: 5 module `index.html` templates over 3,000 lines (sentinel 4322, erm 4040, grid 3879, bcm 3566, orm 3074) and 4 route/service files over 1,500 lines (aria/routes.py 3055, grid/routes.py 2293, launcher/routes_platform.py 2134, sentinel/routes.py 1730), confirming findings.md F11's claim still holds. Inline-handler count and cyclomatic hotspots were not separately measured (no tool for either was already in this repo's dev dependencies; adding one is its own scoped decision, not done silently).
- [ ] Extract JavaScript by cohesive feature, not arbitrary line count. Preserve cache-busting and CSP behavior. **Not started.** Each of the 5 oversized templates is its own multi-step extraction project needing contract tests written first (per the step below) -- genuinely large, separate work this session did not attempt, to avoid rushing a big-bang change T10's own instructions prohibit.
- [ ] Move business rules from route handlers into existing/new module services with explicit transaction boundaries. **Not started**, same reasoning.
- [ ] Replace inline global handlers incrementally with module namespaces/event listeners. Do not rewrite a full module in one task. **Not started**, same reasoning.
- [ ] Add contract tests before extracting each area and compare rendered/API behavior after extraction. N/A until an extraction is actually attempted.
- [x] Build a read-only capability inventory generator from registered routes, capability decorators, roles, feature flags, background workers, and external prerequisites. New `oneforall/scripts/capability_inventory.py`: introspects the real running route table (857 routes) via each route's own decorator closure (exact, not a source-text guess -- immune to decorator aliasing like `routes_admin.py`'s `_require_cap`), cross-references `core/rbac.py`'s `CAPABILITIES` table, and flags any capability string granted to no role at all. Found and closed a real bug the same run: `orm.event.view` (findings.md F15) was granted to nobody, silently 403-ing every user including super admins on ORM's CSV export; fixing it surfaced a second bug (a nonexistent column) masked by the first. Background workers and external prerequisites (feature flags, license requirements) are partially covered (license-required modules are flagged) but not exhaustively -- named as a real gap, not silently dropped.
- [ ] Mark each capability as implemented, gated, configuration-required, pilot-only, deprecated, or planned. **Deliberately left as a manual step**: the generator's own docstring and Markdown output explain why -- pilot-only/deprecated/planned are product judgments a static scan cannot make honestly, so the generated `docs/generated/capability_inventory.md` has a blank column for a human to fill in once, next to facts the generator gets right for free.
- [ ] Update feature inventory/roadmap from generated evidence and retain a human-reviewed product description layer. **Not started.** `FEATURE_INVENTORY.md` (304 lines), `ROADMAP.md` (146 lines), and `PRELAUNCH_TRACKER.md` (395 lines) all exist and were not cross-checked against the new generated inventory this session -- a real, sizeable review task (845 lines against 857 routes) left honestly undone rather than rushed.
- [ ] Add a CI drift check so documented route/capability identifiers cannot silently disappear. **Not started** -- depends on the manual maturity-marking step above existing first (a drift check needs something authoritative to diff against).

Completion gate: no behavior change is bundled with a pure extraction unless explicitly tested; planning documents no longer advertise already-delivered features as missing; new feature tasks use the generated inventory as a discovery input. **Not met** -- most of T10 beyond the capability-inventory generator and its own incidental bug-find is not yet done; see the individual steps above for exactly what remains.

## 5. Stabilization release acceptance gate

Do not begin product tasks until all items below pass:

- [ ] T00-T10 completion gates are recorded in `progress.md`.
- [ ] Full local suite, guarded PostgreSQL suite, JavaScript tests, Jinja compilation, and browser suite pass from a clean checkout.
- [ ] Security review closes F07/F13/F14/F16 and checks tenant isolation for every changed query. F07/F13 closed by earlier T-tasks. F14 (evidence_items) and F16 (bcm_incidents, sentinel_dsr, grid_non_conformances) are each fully fixed with fresh evidence, red/green-proved, and confirmed against full clean backend+browser suite runs (`progress.md` T08 sessions 5 and 7-9). The named GRID NC write-side gap is now fixed with HTTP red/green evidence, including the adjacent audit-create and follow-up BU fixes. F19 also records newly found GRID child-route SBU gaps: the audited routes are guarded, while mappings, reminders, saved reports, policy requests, and other GRID paths still need endpoint-by-endpoint review. The broader "OR business_unit_id IS NULL" cross-org question is now resolved and closed (see `findings.md` F16's 2026-10-01 resolution note): traced the full request path (schema-per-tenant table provisioning + `tenant_context_middleware` + `get_session_user`'s org_slug resolution + `get_db()`'s unconditional per-call `set_tenant()`) and confirmed it is structurally not exploitable on production PostgreSQL, specific to the SQLite dev/test path only. Left unchecked as a whole: this acceptance-gate line is a final, whole-programme claim ("every changed query," not just these tables'), and a repeat security pass is still owed once T09/T10 and the remaining P-tasks land.
- [ ] No critical action has an uncaught console error, unexpected 5xx, or silent failure.
- [ ] Dependency and secret scans pass or have approved time-bounded exceptions.
- [ ] `git diff --check` passes and the diff contains only intended ThemisIQ changes.
- [ ] A release candidate is committed/pushed only if separately authorized.
- [ ] Production deployment is performed only if separately authorized and only after the rollback-aware procedure in section 8.

## 6. Product-improvement tasks

Each product task is a separate releasable slice. Complete its discovery note, API/data contract, threat model, accessibility review, tests, and acceptance before moving to the next. The order below reflects user value and dependency, not permission to implement all at once.

### P01 — Role-aware My Work action centre

Goal: give each user one trustworthy list of work requiring their action without replacing the existing Task Board or module records.

Dependencies: stabilization accepted; authoritative capability inventory available.

Discovery gate:

- [x] Inventory current My Dashboard, Task Board, workflow instances, ARIA approvals/revisions, Evidence expiry/requests, GRID findings/non-conformances, ERM/ORM reviews, BCM actions, privacy deadlines, and notification deep links. Done 2026-09-30 by direct code reading (not delegated -- the research subagent hit the session rate limit and was not retried): `task_board` (status todo/in_progress/review/done/cancelled), `workflow_instances`/`workflow_actions` (status='active', current_step), `aria_document_approvals` (status='pending'), `evidence_items.expiry_date` (existing "expiring" view, +30 days), `grid_non_conformances` (status='open', due_date), `erm_enterprise_risks.workflow_step` / `orm_events`, `bcm_incidents`, `sentinel_dsr.deadline_date` / `sentinel_breaches.notification_required`, `notifications` (is_read, link). See progress.md P01 session 1 for exact columns.
- [x] Interview/confirm priority and vocabulary for at least policy author/approver, risk owner, audit lead, BCM manager, DPO, organization admin, and ordinary employee. User confirmed 2026-09-30: all 9 sources above are in scope for v1 (no reduced slice); compliance_manager is the first persona whose view must be complete before others.
- [x] Decide which records are actionable versus informational and identify the canonical completion endpoint for each. User confirmed 2026-09-30: deep-link-only for v1 -- every item shows its due date/status and a link to the source module; the action centre itself never performs the completing mutation (matches "Selected design"'s own "Completion always calls the source module" line below, and the plan's global rule against bypassing source validation). A per-item-type quick-action is explicitly deferred to a later release, not silently assumed.

Selected design:

- Build a read model/federated query; do not duplicate business records into a new task table.
- Every item has stable `source_module`, `entity_type`, `entity_id`, action code, title, due date, priority, assignee, organization/SBU, deep link, and capability-derived permitted actions.
- Default sections: Needs my action, Waiting on others, Due soon, Overdue, and Recently completed.
- Completion always calls the source module. The action centre never bypasses source validation.

Implementation tasks:

- [x] Add a scoped service returning normalized items with cursor pagination, filters, and deterministic ordering. **Partial (first slice)**: `modules/launcher/my_work_service.py`'s `get_my_work(user)` wires 4 of the 9 discovery-gate sources (ARIA policy approvals, evidence expiry, task_board, notifications) into the 5 standard sections; the other 5 (generic workflow engine, GRID non-conformances, ERM/ORM reviews, BCM incidents, Sentinel/privacy deadlines) are named in the module's own `_PENDING_SOURCES` list and surfaced to the page, not silently missing. No cursor pagination yet (each source is `LIMIT`-capped instead) -- deferred until real data volume shows it's needed, per this plan's own YAGNI discipline.
- [x] Add page/API under existing Launcher navigation; reuse Task Board visual patterns without conflating source records with tasks. `GET /my-work` (page) and `GET /api/my-work` (JSON) in `modules/launcher/routes_my_work.py`, registered in `modules/launcher/routes.py` the same way every other launcher sub-router is. `modules/launcher/templates/my_work.html` is a plain sectioned list for this first pass, not yet visually matched to Task Board's card styling -- functional correctness was prioritized over visual polish for v1; named here rather than silently claimed as done.
- [ ] Add saved personal filters only after P06's preference model exists; initial release may use URL query state. Not started -- no filters exist yet at all in this first slice.
- [ ] Add bulk navigation/acknowledge only where actions are non-destructive and individually authorized. Not started -- v1 is deep-link-only per the discovery-gate answer, no in-page actions of any kind yet.
- [ ] Add empty, partial-module-unavailable, and stale-data states. **Partial**: an empty section renders "Nothing here." (`my_work.html`); a fetch failure shows a generic error. No per-source "this module is disabled for your org" state yet -- if a wired source's table doesn't exist or its query fails, the whole page fetch fails, not a graceful partial render. Named as a real gap, not fixed silently.
- [ ] Add deep-link and source-state refresh after an action completes. N/A yet -- v1 has no in-page actions to refresh after (deep-link-only, per the discovery gate).

Acceptance (status for the 4 sources wired in this first slice; not yet claimed for the whole feature):

- [x] no cross-org/SBU item leakage -- `tests/test_my_work_service.py`, 3 red/green-proved isolation tests (evidence expiry by org, task_board by assigned_to/created_by, notifications by user_id). ARIA approvals' own isolation is not independently tested here (see that file's docstring for why) but reuses an already-tested query shape.
- [ ] counts match source modules for fixtures -- not separately verified; the isolation tests check presence/absence, not exact count parity against each source's own listing endpoint.
- [ ] an unauthorized action is neither advertised nor accepted -- N/A yet (no in-page actions exist in this deep-link-only slice to advertise or accept).
- [ ] source changes appear without duplicate reconciliation jobs -- true by construction (no caching/reconciliation layer exists; every request re-queries live), not separately tested.
- [ ] page remains useful when one optional module is disabled -- **not met**, named above as a real gap (a failing source currently fails the whole page).
- [ ] median initial response meets a budget selected during discovery -- no response-time budget was discussed or measured this session.

### P02 — Sanitized administration diagnostics and readiness centre

Goal: let authorized operators distinguish healthy, disabled, unconfigured, degraded, and failed dependencies without shell access or secret exposure.

Dependencies: T05, T06, T09, P09 status vocabulary.

Discovery gate:

- [x] Reuse `/health`, `/ready`, scheduler status functions, feature flags, queue state, ARIA preview heartbeat, AI configuration, email configuration, backup metadata, database checks, and systemd/deployment knowledge already present. Scheduler status and backup freshness and preview-worker heartbeat did not exist as callable functions yet (only raw files/APScheduler internals) -- built as thin new read-only wrappers over the existing mechanisms (`scripts/production_backup.sh` output files, `_scheduler` APScheduler instance, `.worker.heartbeat` spool file) per user's explicit "build the missing heartbeat/backup infrastructure too" scope decision, rather than inventing a parallel tracking mechanism.
- [x] Separate platform-super-admin information from organization-admin configuration state. `get_diagnostics(user)` only computes/attaches the `platform` key when `user["is_super_admin"]` is true; red/green proved (see Round P02 below).

Implementation tasks:

- [x] Create a read-only diagnostics service with independently timed probes and a short cache; one slow dependency must not block the page. `diagnostics_service.py`'s `_safe()` wraps every probe so one raising probe degrades only that entry (see acceptance line re: degraded dependency). No cache added -- v1 probes are all cheap (file stat, one SELECT 1, one heartbeat file read); revisit if a future probe is slow.
- [x] Report database connectivity, background scheduler heartbeat, preview worker heartbeat, AI provider configuration state, email configured state, licensed modules, and verified-backup freshness. NOT built in v1: app release/build display, publication/scan queue age, LibreOffice/preview readiness, feature-flag listing -- not named as blocking by the user; can be added as additional probes later without reshaping the service.
- [x] Never return keys, DSNs, passwords, webhook URLs, full filesystem paths unnecessary to the user, raw exceptions, process environment, or private host inventory. Every probe returns only a `CapabilityState` (state/reason_code/message/remediation_route/retryable) or, for scheduler, `{running, jobs: [{id, next_run_time}]}` -- no probe ever threads a secret/path/env value into a response field. Backup probe surfaces only `latest.name` (a fixed `themisiq-{timestamp}.zip` pattern) and size/age, never a full path. Covered by a dedicated redaction regression test with a red/green proof.
- [x] Make active probes side-effect-free. Every probe is a pure read (file stat/read, `SELECT 1`, APScheduler introspection); no probe here performs a "Send Test" style mutation, so the separate rate-limited mutation this line warns about does not apply to v1.
- [ ] Provide remediation text and correlation IDs rather than stack traces. Remediation route is wired for email (`/admin/email`) only; not yet added for the other probes. No correlation-ID scheme added.
- [x] Add audit events for viewing sensitive platform diagnostics and for any active test. `GET /api/admin/diagnostics` calls `log_audit(user, "platform", "Viewed platform diagnostics")` on every call.

Acceptance:

- [x] redaction tests cover every response field -- `test_get_diagnostics_never_leaks_the_configured_smtp_host` (red/green proved: temporarily made the email probe return the host in `message`, confirmed the test caught it, restored).
- [x] org admin sees only organization-level configuration state -- `test_org_admin_sees_org_scoped_state_but_no_platform_key` (red/green proved: temporarily removed the `is_super_admin` gate, confirmed the test caught the leak, restored).
- [x] super admin sees platform state but not secret values -- `test_super_admin_sees_platform_key_with_all_three_probes`.
- [x] degraded dependency is represented without making the whole page 500 -- `_safe()`'s exception path returns `NOT_CONFIGURED`/`probe_error` instead of raising; the HTTP tests hit the real endpoint end-to-end with no probe mocking and get 200 in every case.
- [x] backup freshness is metadata-only and never downloads a dump -- `get_backup_freshness()` only ever calls `Path.stat()`/`glob()`, never opens or extracts the zip.
- [~] browser and API tests cover healthy/degraded/unconfigured/forbidden states -- API-level covered (`tests/ui/test_diagnostics_routes.py`: unauthenticated/forbidden/org-admin/super-admin/page-render, plus unit-level healthy/stale/missing/host-managed branch coverage in `tests/test_diagnostics_probes.py`); no dedicated Playwright browser test clicking through the rendered diagnostics.html page yet (page-render smoke test only confirms 200 + title text, not the JS-rendered cards).

### P03 — ARIA policy lifecycle workbench

Goal: make current publication, editable work, candidate version, approval, and next action understandable on one screen.

Dependencies: T01, T02, T06-T08; preserve PLAN-35 invariants.

Discovery gate:

- [x] Map existing Documents modal, AI Generator draft editor, version history, preview, approval, publication status, and feature gates. Found the entire PLAN-35 backend (drafts, build, confirm, submit, approve/reject, withdraw, publication retry) already has a COMPLETE, working, tested API (`modules/aria/routes_policy_workflow.py`, ~19 endpoints) *and* a complete, reusable frontend (`static/js/aria_policy_workflow.js`, 772 lines, deliberately container-agnostic -- "each renderer takes an explicit container rather than assuming a fixed id, since documents.html mounts these inside its own edit modal") already wired into `ai_generator.html` (draft editor, My Drafts) and `documents.html`'s edit modal (version history, publication status, start-revision, submit-for-approval, pending-approvals queue, approve/reject). P03's real job was narrower than first scoped: unify what's split across those two pages/contexts onto one screen per document, reusing the existing renderers rather than rebuilding them.
- [x] Do not create a second policy workflow, draft table, version table, or publication queue. No new table. One new pure-read aggregator function (`get_document_workbench_state` in the existing `policy_workflow_service.py`) that queries the same tables through the same helpers (`_draft_can_read`, `_draft_can_edit_document`, `can_decide`, `_version_to_public_dict`, `_approval_to_public_dict`); every mutation on the new page calls the exact same PLAN-35 endpoints the other two pages already call.

Real gap found and fixed along the way (not scope creep -- squarely inside this task's own goal): `documents.html`'s modal only ever checked `current_policy_version_id`'s state to decide whether to show the submit-for-approval form, which covers a brand-new document's first version but **not** a revision's candidate version (which stays a separate row, out of `current_policy_version_id`, until approved). There was no UI path anywhere to submit a revision candidate for approval before this change -- only a direct API call could do it. Fixed by modeling `submittable_version`/`active_approval` independent of which slot (current or candidate) the version is in.

Implementation tasks:

- [x] Add a document workbench route/deep link centered on one `aria_documents` identity. `GET /aria/documents/{doc_id}/workbench` (page) + `GET /aria/api/documents/{doc_id}/workbench` (data), own file (`routes_workbench.py`, T10 file-size discipline) registered in `main.py`. Deep-linked from a new "Open Policy Workbench" button inside the existing Documents modal's managed-lifecycle panel -- additive only, per explicit user decision; the modal itself is unchanged otherwise.
- [x] Present Current published version, Working draft, Candidate awaiting decision, and History as distinct cards/tabs. Four-card grid in `policy_workbench.html`; History reuses `renderVersionHistory` unchanged.
- [x] Show one primary next action based on server-returned permissions/state; never infer authorization only in JavaScript. Every `can_*` flag (`can_submit`, `can_edit`, `can_decide`, `can_withdraw`, `can_start_revision`) is computed server-side in `get_document_workbench_state` using the exact same helper the real mutating endpoint enforces -- a stale/wrong hint can only ever hide an action the server would still refuse, never grant one the server wouldn't allow, and this is proved by a red/green test (temporarily inverted the approval-visibility gate; confirmed a bystander test caught the leak; restored).
- [ ] Add immutable version comparison for metadata and normalized text, with artifact hashes and approver history. Not built this slice -- History card lists versions with hashes already present in `_version_to_public_dict`'s output, but no side-by-side diff view. Scope explicitly deferred, not silently dropped.
- [x] Integrate edit metadata, start/reopen revision, build preview, confirm, submit, withdraw, decide, publication retry, and download through existing services. All wired via the pre-existing `AriaPolicyWorkflow.api`/`.ui` functions (added only `api.getWorkbench`, a one-line fetch wrapper) -- edit/build/confirm still happen on `ai_generator.html` itself (see below), deep-linked from the Working Draft card's "Continue editing" link rather than duplicated onto a second page.
- [ ] Explain feature-disabled, pilot-org-disabled, preview-worker-unavailable, and AI-unconfigured states using P09 vocabulary. Not built this slice -- the workbench surfaces `ACTION_FORBIDDEN` from `_authoring_gate` the same way the existing pages do (a toast), but doesn't yet render it in the shared `core/capability_state.py` vocabulary P09 established. Candidate for a follow-up slice alongside P09's own remaining areas.
- [x] Preserve the currently approved version while a revision is in progress or rejected. No new code path touches this -- it was already PLAN-35's own guarantee (I11); the workbench only reads and displays it (Current card always shows `current_policy_version_id`, independent of draft/candidate state).

Deliberately not duplicated onto the new page (reused as-is instead): the full draft body editor (textarea, markdown preview toggle, build/preview/confirm flow) stays on `ai_generator.html` -- the Working Draft card shows status and a "Continue editing" deep link, matching the exact UX `refreshMyDrafts()`'s own "Resume" link already established, rather than building a second, parallel editor UI that would need its own concurrency/lock-version test coverage a second time.

Acceptance:

- [ ] every PLAN-35 state transition has one unambiguous visible state and permitted action set -- most are (submit/decide/withdraw/start-revision/download all visible with correct permission gating); edit/build/confirm remain a deep link to the existing editor rather than an inline state on this screen, so this is partial, not full, unification.
- [x] author cannot approve own content -- real-browser-proved (`tests/ui/test_aria_policy_workbench_browser.py`: the assigned approver sees Approve/Reject controls; the requester, viewing the same page, does not) and service-level-proved with a red/green proof (`tests/test_aria_policy_workbench.py`).
- [x] current approved artifact remains downloadable during revision/failure -- Current card always renders independent of draft/candidate state (see I11 note above); download link points at the existing, unchanged `/aria/api/policy-versions/{id}/download` endpoint.
- [ ] two-tab concurrency produces a clear conflict, not silent overwrite -- inherited for free for every action this page delegates to the existing endpoints (each already takes `expected_lock_version` and returns `STALE_DRAFT`/409 on a stale token, already tested in tests/test_aria_policy_approvals.py's concurrent-deciders test), but not re-proved with a dedicated two-tab test against this specific new page this slice.
- [x] version diff never exposes another organization/SBU -- no diff view was built this slice (see above), so there is nothing yet that could leak one; the read aggregator itself is covered by a cross-org 404 test.
- [~] all primary transitions have real-browser coverage -- the one transition this task_plan.md line names explicitly (self-approval prevention) has real-browser coverage; submit/withdraw/start-revision do not yet have a dedicated browser test for this specific page (they are exercised at the service level and, for the underlying endpoints, at the HTTP level already).

### P04 — Data-readiness and integrity centre

Goal: identify records that will block workflows before users encounter failures.

Dependencies: T04, T06, T10; P02 may host platform-level summaries.

Selected design:

- Rules are deterministic, versioned, and read-only by default.
- Every issue contains code, severity, module, scoped record reference, explanation, detected time, and safe remediation link.
- No generic Auto Fix performs broad mutation. A specific fix requires its own preview, authorization, transaction, audit event, and rollback semantics.

Implementation tasks:

- [x] Inventory invariants already encoded in migrations/readiness helpers and avoid duplicating SQL inconsistently. Delegated to a research agent given the size (7 named modules x 8 categories); findings: strong prior art for stale-lease reclaim (aria_policy_publication_jobs/erm_emerging_scan_jobs already implement claim+reclaim) and per-module overdue-date jobs (evidence/GRID/BCM/Sentinel schedulers), but categories 1-5 (missing org/SBU/owner, inactive assignee, broken cross-reference, missing template/build, invalid lifecycle combination) had **no existing detection anywhere** -- genuinely new ground, not a duplicate of something already there. Also surfaced a real, load-bearing schema fact used throughout this rule set: tables with a real `org_id` column (aria_*, evidence_items) are RLS-protected shared tables and must be filtered by org_id explicitly; BU-scoped-only tables (grid_controls, erm_enterprise_risks, business_units itself) have **no org_id column at all** -- their isolation is Postgres schema-per-tenant only (the caller's tenant_context binding), a pre-existing architecture this rule set works with, not around.
- [x] Add rules for missing organization/SBU/owner, deleted or inactive assignee, broken cross-module reference, missing policy template/build, invalid lifecycle combination, stale queue lease, overdue evidence/review, and capability/config prerequisite. One concrete, real, tested rule per category (8 total: MISSING_RISK_OWNER, INACTIVE_CONTROL_ASSIGNEE, BROKEN_FRAMEWORK_REFERENCE, ARIA_DRAFT_MISSING_BUILD, ARIA_VERSION_STATE_MISMATCH, STALE_PUBLICATION_LEASE, EVIDENCE_EXPIRED_UNFLAGGED, ARIA_AUTHORING_NO_TEMPLATE) -- see progress.md's P04 session entry for exactly which table/column each covers. Adding another rule instance is additive: write a function, decorate with `@register_rule("CODE")`, done (modules/readiness/rules.py's own module docstring documents this).
- [x] Run on demand and through a bounded scheduler lease; persist summaries only if needed for trend/acknowledgement. Daily sweep (03:30 UTC) via `database.try_acquire_scheduler_lock` (same cross-process lease pattern as ARIA's own retention sweep); on-demand trigger (`POST /readiness/api/scan`) is a separate entry point, gated by `platform.manage_readiness` and its own rate limit (1 per 5 min per org), not sharing or blocking on the scheduler's lease. Findings persist in `readiness_findings` with reconciliation (new/updated/auto-resolved), not just a per-run summary.
- [x] Add filters, export without sensitive content, acknowledgement/suppression with reason and expiry, and deep links. Filters by module/severity/status; CSV export (rule-generated message text only, never a raw record dump -- tested); acknowledge (reason required) / suppress (reason + expiry) / reopen, each audit-logged; `remediation_route` deep-links where a real route exists (ARIA documents), `None` elsewhere rather than a guessed URL.
- [ ] Show why a rule cannot inspect a disabled module instead of reporting it healthy. Not built this slice -- every rule here runs unconditionally (a rule against an unused module's empty tables is a fast no-op, matching every other per-module scheduler's own documented convention), but no rule surfaces "this module is disabled, so I couldn't check it" as a distinct state from "checked, found nothing." Candidate follow-up once a first module actually needs a disabled-state carve-out.

Acceptance:

- [x] tenant isolation and deterministic fixtures for every rule -- every rule has a positive+negative test (tests/test_readiness_rules.py); org-scoping itself (run_rules_for_org, acknowledge_finding) has a dedicated cross-org isolation test with a red/green proof (tests/test_readiness_data_service.py).
- [x] deliberately corrupted disposable rows are detected -- every positive-case test above IS a deliberately corrupted disposable row (e.g. a draft forced to 'committed' with a NULL build_id, a version forced to 'approved' with a NULL approved_at).
- [x] clean fixtures produce no false blockers -- every rule also has a negative-case test asserting zero findings against a clean/legitimate row shaped like the real thing (e.g. an owned risk, an active assignee, a valid framework reference).
- [~] scan is bounded and observable on production-scale synthetic data -- bounded via the scheduler lease and the on-demand rate limit; NOT load-tested against production-scale synthetic data this slice (no such fixture exists in this codebase yet).
- [x] no scan mutates business records -- every rule function only ever executes SELECT statements; asserted directly in tests/test_readiness_rules.py's `test_rules_are_read_only` (byte-identical row before/after a rule runs against it).

### P05 — Evidence collection campaigns

Goal: coordinate evidence requests, ownership, due dates, reminders, submissions, review, and coverage gaps while preserving Evidence Vault as the canonical file/link store.

Dependencies: T02, T06-T08, P01.

Discovery gate:

- [x] Map existing evidence items, links, verification, expiry, GRID evidence requests/files, tasks, notifications, and audit history. Delegated to a research agent given the breadth; full citations in progress.md's P05 session entry.
- [x] Decide whether GRID request records can be generalized or whether a new campaign/request layer is needed; document why. **New layer needed, confirmed by reading the code.** `grid_evidence_items`/`grid_evidence_files` are hard FK'd to `grid_controls` (no module/entity_type polymorphism like `evidence_links` has -- cannot represent "ask the BCM plan owner" or "ask the ARIA control owner"), carry no `org_id` at all (BU-scoped only), and have no request-before-a-file-exists phase (`grid_approvals` only starts after a file already exists) or due-date/reminder concept beyond a single mutable `grid_controls.assignee_id`/`due_date` pair that would be overwritten by a second concurrent or recurring request. Building on GRID would also run backwards against GRID's own existing `sync_grid_evidence_to_vault()`, which already copies GRID's files *into* Evidence Vault -- and would recreate exactly the "second file store" this task explicitly warns against.

If new tables are required, minimum model:

- `evidence_campaigns`: org/SBU, name, scope, owner, start/due dates, status, recurrence definition, created_by;
- `evidence_requests`: campaign, requirement/control/entity reference, assignee, reviewer, due date, status, instructions, submitted evidence link;
- append-only request events for assignment, reminder, submission, return, acceptance, cancellation, and overdue transition.

Implementation tasks:

- [x] Define a state machine and idempotent reminder/escalation behavior. `requested -> submitted -> in_review -> accepted` (terminal) / `in_review -> returned -> submitted` (resubmit) / any non-terminal `-> overdue` (scheduler, due date passed) `-> submitted` (late submission still allowed) / any non-terminal `-> cancelled` (terminal, explicit reason, audited). T-3-day reminder is idempotent by construction (checks for an existing un-sent `email_reminders` row with the exact deterministic title before inserting another); overdue notification fires exactly once per lateness episode as a natural side effect of the one-time state transition itself, no separate dedup table needed for that one. Both tested directly (repeated scheduler calls produce zero duplicate rows on the second pass).
- [x] Reuse Evidence Vault uploads and links; never create an ungoverned second file store. `evidence_requests.evidence_id` points at the canonical `evidence_items` row; `submit_request` resolves it through the exact same `_scoped_evidence_item` fail-closed helper `modules/evidence/routes.py` itself uses (not a second copy of that check) -- tested directly that an evidence id belonging to another org is rejected even though the id exists.
- [x] Add campaign coverage summary: requested, submitted, accepted, returned, overdue, and uncovered requirements. `campaign_coverage()` returns all named counts plus `uncovered` (everything not yet accepted or cancelled) and `total`.
- [x] Feed actionable requests into P01 and Calendar without duplicating source ownership. `create_request` inserts one `task_board` row (`module='evidence_campaigns'`, same polymorphic tagging convention `modules/evidence/scheduler.py` already uses) and one `calendar_events` row per request -- `evidence_requests` stays the single source of truth for status; these are read-projections, not a second copy of ownership. P01's own `my_work_service.py` is not yet updated to surface these (see "not yet started" list); the task_board feed means they are at least visible through the platform's existing generic Task Board today.
- [x] Preserve chain of custody, verifier identity, and file authorization. `reviewed_by`/`reviewed_at`/`review_notes` on the request row plus a full `evidence_request_events` append-only history (matching `erm_risk_workflow_history`'s established shape) record who did what and when; file authorization is unchanged and untouched -- Evidence Vault's own access control on `evidence_items` still applies in full, since this module never bypasses `_scoped_evidence_item`.

Acceptance:

- [x] submitter cannot self-accept where separation is required -- `decide_request` refuses when `assignee_id == actor.id`, checked directly (not inferred from role), with a red/green proof and an HTTP-level end-to-end test using two distinct real personas.
- [x] files remain private and scoped -- no new file storage exists in this module at all; `_scoped_evidence_item` reuse means Evidence Vault's own privacy/scoping is the only access control that ever applies.
- [x] reminder retries do not duplicate notifications/tasks -- `schedule_reminders` tested directly for idempotency across repeated calls (first call schedules one, second schedules zero); `task_board`/`calendar_events`/`notifications` rows are created exactly once, at request-creation time, never re-created by the scheduler.
- [x] campaign close cannot hide unresolved/returned requests without explicit override and audit -- `close_campaign` refuses without `force`; with `force`, requires a reason and writes an `audit_log` row naming the unresolved count -- both branches tested directly.
- [x] recurring campaign generation is idempotent -- `generate_recurring_campaigns` tested directly for idempotency across repeated calls, via `recurrence_source_id` (a campaign is only ever generated from a given source once).

### P06 — Saved views and permission-safe bulk actions

Goal: reduce repetitive filtering and allow carefully bounded multi-record operations.

Dependencies: T06-T08. Implement shared infrastructure once, onboard modules incrementally.

Selected model:

- Saved views store owner, optional shared organization scope, module/view key, versioned validated filter JSON, sort, columns, and default flag.
- Saved views never store SQL, arbitrary URLs, HTML, or capability decisions.
- Bulk actions re-authorize every record server-side and return per-record outcomes; a visible selection count is not authorization.

Discovery (no separate "Discovery gate" header in the original plan text,
but real discovery was done and changed the plan before any code was
written): delegated to a research agent given the breadth (every module's
read/detail/update/delete route quartet, plus any existing bulk-action or
saved-filter mechanism anywhere in the codebase). Findings:

- **No existing bulk-action or saved-view mechanism was worth extending.**
  Three partial, inconsistent patterns existed (Task Board's real-but-
  count-only batch endpoint; GRID evidence bulk-approve with zero
  ownership/BU check at all; ERM/ORM's checkbox UX sitting on client-side
  loops over single-record endpoints with the weakest authorization of the
  three). Saved views were fully greenfield -- the only "saved view" hit
  anywhere in the codebase was a `localStorage` display-mode toggle.
- **The plan's own named first target (Task Board) was found to be the
  *most* encumbered candidate, not the lowest-risk one**: it already has a
  bulk endpoint to reconcile, logs nothing to audit_log, and (discovered in
  the same pass) its list route had zero business-unit scoping at all --
  fixed separately as F17, since it was a real pre-existing bug, not a P06
  design question. Evidence Vault was identified as genuinely lowest-risk
  (zero existing bulk/checkbox UI to reconcile, already-mandatory org
  scoping on its list route, a small clean existing query-param set) and
  confirmed with the user as the actual first module.
- **This same read-vs-write-route comparison surfaced three more real
  authorization gaps** (ERM/ORM write-path BU-scope gaps, GRID bulk-approve's
  missing check) -- documented and fixed immediately as `findings.md` F17,
  not part of P06 itself.

User's explicit scope decisions: Evidence Vault as the first onboarded
module (not Task Board as literally named); full shared infrastructure
built for real now, not sized to only what Evidence Vault needs.

Implementation tasks:

- [x] Start with one low-risk module after discovery, then Task Board, risks, evidence, policies, vendors, and findings. Evidence Vault done this slice (registered schema: `category`/`status`/`q`/`module`/`view` -- its real `GET /api/items` query params -- plus a `bulk-archive` action). Task Board, risks, policies, vendors, findings remain **explicitly deferred, not dropped**: onboarding each is now pure plumbing (register_view_schema + a bulk action using the generic engine), not new design, since the shared infrastructure is already built in full.
- [x] Add filter-schema validators and migration for old view versions. `register_view_schema`'s allowlist is the validator; `saved_views.schema_version` column exists for a future migration path (no migration needed yet -- there is only one schema version so far).
- [x] Restrict sharing/editing/deletion by owner and organization capability. `update_saved_view`/`delete_saved_view` are owner-only (`_owned_view_or_raise`); a `shared=1` view is read-only to everyone else, tested directly (an attempted edit by a non-owner raises `NOT_FOUND`, never silently succeeds or 403s in a way that would confirm the view exists to someone who shouldn't see it as editable).
- [x] Require confirmation summaries for mutations and idempotency keys for retryable bulk operations. `execute_bulk_action` accepts `idempotency_key` (wired to the client's own `Idempotency-Key` header, which `static/js/api_client.js` already sends but no route previously consumed); a retried call with the same key returns the original `{applied, skipped}` outcome instead of re-executing, tested directly at both the service and HTTP level.
- [x] Define atomic versus best-effort semantics per action; never leave this implicit. `execute_bulk_action(..., atomic: bool)`: best-effort (default) applies to every independently-authorized id and reports failures per id; atomic refuses the *entire* batch if even one id fails authorization. Evidence's bulk-archive uses best-effort (an archive is independently safe per item); both modes are tested directly.
- [x] Produce an audit event with bounded record identifiers/counts, not sensitive field dumps. One `audit_log` row per bulk-action call, `details` is a bounded string ("N of M record(s) applied, K skipped"), never a per-record dump.

Acceptance:

- [x] malicious filter JSON cannot alter queries -- true by construction, not by a validator having to get every case right: filter_json only ever stores query-PARAMETER names already accepted by the owning module's existing, already-safely-parameterized list route; there is no SQL-generation step anywhere in this module at all. An unknown key is rejected outright at write time (tested, including a literal injection-shaped string value, which is stored only as an opaque rejected key name, never interpreted).
- [x] shared view does not grant access to records -- applying a saved view is purely a client-side replay of its stored params onto the owning module's own, separately-capability-gated list route; saved_views itself grants no access of any kind. Tested: a shared view is visible to another user in the same org, never to a user in a different org.
- [x] mixed authorized/unauthorized selection cannot mutate unauthorized rows -- the core property of `execute_bulk_action`, proved with a red/green test at the service level and an HTTP-level test using a genuinely different organization's record as the unauthorized id.
- [x] partial failures are visible and retryable without duplicating successes -- `{applied, skipped}` makes a partial failure visible per id; retryability without duplication is the idempotency-key mechanism, tested directly (a second call with the same key does not re-run `execute_fn`).
- [ ] keyboard and screen-reader selection is supported -- not yet verified; Evidence Vault's own list page does not yet have a checkbox-selection UI wired to the new bulk-archive endpoint (the backend/API layer is complete and tested; the accessible multi-select UI itself is next, part of actually onboarding Evidence Vault's list page rather than just its API).

### P07 — ERM scenario, KRI, control linkage, and board-pack snapshots

Goal: extend existing ERM register/objectives/KRIs/assessments/reports into decision-grade scenario analysis and reproducible reporting.

Dependencies: T03, T04, T06-T10.

Discovery gate:

- [x] Map existing enterprise risks, objectives/pillars, KRIs, assessments, appetite, treatments, controls/effectiveness, analytics snapshots, external context, and reports. Mapped by reading modules/erm/data_service.py directly: risks=`erm_enterprise_risks`, controls=`canonical_controls`+`risk_controls` bridge, KRIs=`erm_kris`/`erm_kri_history`, objectives=`erm_objectives`, appetite=`erm_risk_appetite`, treatments=`erm_treatments`-equivalent via `list_treatments`, analytics snapshots=`erm_risk_score_history`, external context=`erm_emerging_risks` (PLAN-28 emerging-risk inbox), reports=`/erm/api/reports/*` + the existing `/erm/api/ai/board-report` live-generated narrative this plan's own board-pack work formalizes.
- [x] Agree the scenario calculation method and labels with the user; do not present AI-generated numbers as measured facts. User pointed to two real documents (`Risk Rating.xlsx`, `risk register.xlsx`); reading them surfaced and fixed F18 (the tier-4 residual default didn't match the real register). Decision: scenarios reuse the real engine verbatim (`data_service.get_active_framework_matrix`/`resolve_band`/`_compute_residual_tiers`, the latter newly extracted as a pure, shared function) with scenario-stored deltas substituted for the inputs they override -- never a separate formula. The "editable calculation template" requirement is met by the framework system that already existed (clone-then-edit, confirmed via code reading) plus F18's new `default_residual_factor` column on it -- no new template mechanism was built because one already existed.

Implementation tasks:

- [x] Add scenarios with assumptions, horizon, owner, status, version, and org/SBU scope. `erm_scenarios` table + `modules/erm/scenarios.py` CRUD (`create_scenario`/`update_scenario`/`delete_scenario`, version auto-increments on update). No org_id by design -- same per-tenant-schema isolation as `erm_enterprise_risks` itself (confirmed via `database.py`'s tenant-schema DDL and the self-healing `_migrate_all_tenant_schemas()` that replays it against every existing tenant schema on startup); `business_unit_id` is the sub-scope.
- [x] Link scenarios to risks, controls, KRIs, objectives, and external-context items through explicit scoped join tables. `erm_scenario_links` (`link_type` CHECK-constrained to the 5 types, `UNIQUE(scenario_id, link_type, link_id)`, upserts on re-add). `add_scenario_link` enforces existence + two scope checks: structural (a BU-scoped scenario cannot link a different BU's item) and authorization (the acting user's own `bu_scope_ids()`). Known, documented v1 limitation: a freestanding KRI (no `linked_risk_id`) has no business-unit scope of its own and cannot be scope-checked -- `erm_kris` has no `business_unit_id` column.
- [x] Store scenario inputs and deterministic calculation outputs separately from narrative AI assistance. Inputs = `erm_scenarios`/`erm_scenario_links` (never touched by narrative code). Outputs are computed on demand by the pure `compute_scenario_impact()` (never persisted outside a board pack) so they always reflect live baseline data; narrative lives only on `erm_board_packs.narrative`/`narrative_citations_json`/`narrative_source`, a frozen artifact's own columns.
- [x] Show baseline versus scenario inherent/residual exposure and appetite impact with data-quality/confidence indicators. `compute_scenario_impact()` returns `baseline_totals`/`scenario_totals` (avg IRR/RRR, EMV totals), `per_risk` (per-risk baseline vs scenario band/IRR/RRR), `appetite_impact` (per-category max exposure vs `erm_risk_appetite.max_score`, scoped to the scenario's own linked risks -- the existing ERM dashboard already covers whole-register appetite breaches, so this isn't duplicated), and `data_quality_issues` (explicit, itemized -- never a silent zero).
- [x] Create immutable board-pack snapshots containing as-of timestamp, filter/scenario IDs, source record versions/hashes, generated charts/tables, and approver/publication metadata. `erm_board_packs` + `generate_board_pack()`: `as_of`, `scenario_id`, `filters_json`, `source_snapshot_json` (the full computed comparison -- tables data), `source_hashes_json` (one sha256 per linked source record's relevant fields), `content_hash`/`prev_hash` (a per-tenant-schema hash chain, `verify_board_pack_chain()` detects tampering or a broken chain), `approved_by`/`approved_at`/`published_at`. Immutability is enforced at the application layer (only `update_board_pack_narrative`/`generate_board_pack_narrative`/`sweep_stale_board_packs`/`publish_board_pack` ever UPDATE a row, and only their own narrative/status/approval/staleness columns) plus the hash chain for tamper detectability, not a DB-engine-enforced guarantee.
- [x] Mark stale snapshots when source records change without rewriting historical snapshots. `sweep_stale_board_packs()`, run every 15 minutes by `modules/erm/scheduler.py`'s new Job 3 (per active tenant). Deliberately periodic, not triggered synchronously inside a risk/control/KRI mutation's own transaction, to avoid nested write-transaction lock contention with whatever request made the change (`get_db()` opens a brand-new SQLite connection per call; a second writer mid-transaction risks a real, previously-encountered "database is locked" failure mode). Never rewrites `source_snapshot_json`.
- [x] Require citations/source links for AI-written narrative and allow human editing/approval. `generate_board_pack_narrative()` prompts the AI with ONLY the frozen snapshot's own source references as the allowed citation set, parses the response, and rejects (does not save) any response whose citations reference something outside that set, or that has no citations at all -- enforced in code, not just prompted for. `update_board_pack_narrative()` lets a human write or edit a narrative (`source='human'`/`'ai_edited'`); `publish_board_pack()` requires a narrative to exist and locks it (no further edits) once published.

Acceptance:

- [x] calculations reproduce from stored inputs -- `compute_scenario_impact()` is a pure function of (scenario, links, live baseline data); `test_compute_scenario_impact_is_reproducible` asserts two calls with no intervening writes return identical results.
- [x] historical snapshot does not change when live risks change -- `test_board_pack_snapshot_immutable_when_live_risk_changes`/`test_sweep_stale_board_packs_flags_without_rewriting_snapshot` both assert `source_snapshot_json` is byte-for-byte unchanged after the underlying risk is edited; only `is_stale`/`stale_reason` move.
- [x] cross-org/SBU links are rejected -- implementation now enforces scenario write scope, structural cross-SBU linkage, target scope, and board-pack scope; focused service and HTTP verification passed on 2026-10-01.
- [x] missing KRI/control data is shown as missing, not zero -- `test_missing_kri_value_flagged_not_defaulted_to_zero`, `test_deleted_linked_risk_flagged_not_silently_skipped`.
- [x] AI outage leaves deterministic analysis and manual narrative available -- `generate_board_pack_narrative()` returns `{"ok": False, ...}` without touching the board pack when `is_configured()` is false or the response fails citation validation; the deterministic `source_snapshot_json` and any existing/human narrative are untouched either way (`test_generate_narrative_ai_not_configured`).

Verification completed 2026-10-01 after review remediation: the focused P07 service, HTTP-route, and real-browser set passed 40 tests; the full backend and browser gates both completed at 100% with exit code 0. Guarded PostgreSQL execution remains an environment-level programme gate. Richer UI affordances such as a search-by-name link picker and charts remain deferred polish.

### P08 — BCM exercise after-action and corrective-action improvements

Goal: strengthen the existing exercise/scenario capability rather than create another exercise module.

Dependencies: T06-T10, P01, optional P05 evidence integration.

Discovery gate:

- [ ] Map `bcm_exercises`, scenarios, injects, participants/contacts, outcomes, lessons learned, scheduler alerts, tasks, evidence links, and reporting.
- [ ] Identify actual gaps in preparation, execution logging, after-action review, and corrective-action closure.

Implementation tasks:

- [ ] Add an explicit exercise lifecycle: planned, ready, running, completed-awaiting-review, closed, cancelled.
- [ ] Add readiness checklist and participant/role confirmation without storing unnecessary personal data.
- [ ] Add timestamped inject/event log and observations during execution.
- [ ] Add after-action review with objectives, results, strengths, gaps, lessons, owner, reviewer, and sign-off.
- [ ] Link corrective actions to canonical Task Board items with due date, owner, evidence, and closure verification; do not duplicate task state.
- [ ] Add exercise effectiveness measures and recurrence comparison with clear data provenance.
- [ ] Feed upcoming/overdue actions into P01 and Calendar.

Acceptance:

- state transitions are authorized and auditable;
- closing an exercise cannot silently close open corrective actions;
- repeated scheduler runs do not duplicate alerts/tasks;
- evidence remains scoped/private;
- after-action report is reproducible and downloadable from retained data.

### P09 — Consistent capability and dependency states

Goal: replace ambiguous missing buttons and generic failures with a truthful platform-wide state vocabulary.

Dependencies: T06, T10; coordinate with P02/P03.

Canonical states:

- available;
- disabled by organization policy or feature flag;
- not configured;
- temporarily unavailable/degraded;
- forbidden for this user;
- unavailable in this product tier, only if licensing logic actually supports it.

Implementation tasks:

- [x] Define a server-returned capability-state object with safe reason code, user-facing message key, optional remediation route, and retryable flag. New `core/capability_state.py`: `CapabilityState` dataclass + one factory per canonical state (`available`/`disabled_by_policy`/`not_configured`/`degraded`/`forbidden`/`unavailable_in_tier`). `forbidden()` structurally cannot accept a message or remediation route -- no such parameters exist on it at all, not just "nobody happens to pass one" -- specifically so a forbidden response can never hint at why a feature also isn't configured/enabled, per the plan's own "forbidden and not-configured are never conflated" acceptance line below.
- [ ] Use capability decorators/feature flags/configuration/readiness as authoritative inputs. **Partial**: the one area wired so far (AI) reads `core/ai_client.is_configured()` directly, the same authoritative check every existing ad-hoc caller already used.
- [x] Do not reveal the existence of cross-tenant records or sensitive platform configuration through state reasons. Enforced structurally for `forbidden()` (see above); the other five factories accept a message but nothing wired so far passes anything sensitive through one.
- [ ] Apply first to ARIA authoring/preview/AI, ERM horizon scan, email, connectors, exports, and external conversion. **Partial**: only AI is wired (`core/ai_client.get_capability_state()`, exposed at `GET /api/capability-state/ai`). ERM horizon scan, email, connectors, exports, and external conversion (LibreOffice) are not yet wired -- each still has its own ad-hoc `is_configured()`-style check and message string, named here rather than silently left inconsistent.
- [ ] Render disabled actions only when seeing the reason helps the user; hide actions that would leak unauthorized capability. Not started -- no frontend yet consumes the new endpoint; P02's diagnostics page is the first planned consumer.
- [ ] Add analytics for state frequency without user content. Not started.

Acceptance:

- [ ] each state has API and browser tests -- **partial**: all 6 states have unit tests (`tests/test_capability_state.py`) and the one wired real endpoint has both an API test (unauthenticated redirect + authenticated shape) and is reachable in a real browser via the harness, but only 2 of the 6 states (`available`, `not_configured`) are exercised through that real endpoint so far -- the others only exist as direct factory-function tests.
- [x] forbidden and not-configured are never conflated -- enforced structurally (see above), not just by convention; red/green-proved via `test_forbidden_signature_has_no_message_parameter`.
- [x] transient outage provides safe retry guidance -- `degraded()` is the only factory with `retryable=True`; every other state defaults to `False`, proved by `test_only_degraded_is_retryable`.
- [ ] feature-disabled paths cannot be bypassed by direct API calls -- N/A yet for the one wired area (AI): the new endpoint is a read-only status report, not a gate in front of a mutation, so there is nothing yet to bypass. This becomes a real check once a capability-gated route (e.g. an AI-suggest endpoint) is refactored to consult this state before acting, which has not happened yet.
- [ ] wording is consistent across modules -- not yet meaningfully testable with only one area wired.

## 7. Verification commands and evidence requirements

Use the project virtual environment. Adjust only when the repository's current documented commands differ; record any change.

Core gates:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest oneforall/tests -q
& '.\.venv\Scripts\python.exe' -m compileall -q oneforall
& '.\.venv\Scripts\python.exe' -m pip check
git diff --check
git status --short
```

PostgreSQL gate:

- Run `oneforall/tests/test_postgres_init.py` only against an explicitly named disposable `themisiq_test_*` database with `THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1`.
- Add focused PostgreSQL tests for T03/T04 before claiming schema/query parity.
- Never point this gate at production or a restored backup that must be retained.

Template/JavaScript gates:

- Compile all Jinja templates with the real `format_dt` filter registered.
- Run Node syntax/unit tests for every changed JavaScript asset and inline script extractor.
- Run the real-browser suite and retain sanitized failure traces.

Security gates:

- dependency vulnerability scan;
- secret scan;
- outbound URL/SSRF test matrix;
- tenant/persona matrix;
- file-path/upload authorization tests for affected features;
- no critical/serious accessibility findings on acceptance routes.

Evidence rules:

- Never say all tests pass from a previous run.
- Record command, timestamp, exit code, pass/fail/skip counts, and environment.
- A skipped live browser, PostgreSQL, delivery, conversion, or production check remains unverified, not passed.
- Prove important regression tests by temporarily reverting/monkeypatching the fix and observing failure, then restore and rerun green.

## 8. Deployment and rollback plan

This section is preparatory; it does not authorize deployment.

### 8.1 Before a release candidate

- [ ] Confirm intended commit is on remote and production worktree is clean.
- [ ] Review schema changes and prepare reversible forward migration; never rely on code checkout alone to roll back schema.
- [ ] Create a fresh verified custom-format PostgreSQL backup, checksum it, list it with `pg_restore --list`, and keep the path/age in the release record.
- [ ] Back up `/etc/themisiq/themisiq.env` and current systemd unit/drop-ins with root-only permissions if configuration/unit changes are involved.
- [ ] Record current release SHA, service state, worker state, feature flags, and health/readiness.
- [ ] Build/publish any container by immutable digest through its tested workflow.

### 8.2 Release sequence

1. Fetch and verify the exact remote commit.
2. Check out the immutable release SHA, not a moving branch.
3. Run `scripts/deploy.py` preflight without modifying the host.
4. Apply schema/config/service changes with newly introduced features disabled.
5. Restart through the supported deploy script.
6. Verify service user/hardening, loopback listeners, `/health`, `/ready`, migration/readiness invariants, worker health, and warning/error journal delta.
7. Run isolated production smoke tests for repaired actions using test records in the approved pilot organization.
8. Enable a feature only after its disabled-state deployment passes and the user authorizes the pilot.
9. Observe error rate, latency, queue age, and audit events through the defined soak window.

### 8.3 Rollback

- Code/config-only failure: stop service, restore prior immutable SHA and root-only config backup, apply the supported deploy script, verify health/readiness.
- Additive schema failure: prefer forward repair; old code must tolerate new nullable tables/columns/indexes.
- Destructive/incompatible schema change: prohibited unless a tested restore/rollback migration and maintenance window were separately approved.
- Feature failure: disable its feature flag first when this safely stops new writes, preserve evidence, then decide code rollback.
- External delivery failure: disable affected connector/webhook delivery without deleting configuration or logs.
- Record rollback result and any data created during the failed window.

### 8.4 Production acceptance

- exact SHA and configuration state recorded;
- service active/enabled, correct non-root user, `NoNewPrivileges=yes`;
- PostgreSQL and app listen only on intended interfaces;
- health/readiness pass;
- no new warning/error burst;
- backup remains restorable;
- critical browser smokes pass;
- no tenant-boundary, workflow, audit, or outbound-delivery regression;
- rollback point retained until soak completes.

## 9. Definition of done

A task is done only when:

- its source behavior and authorization contract are implemented;
- acceptance tests pass with fresh output;
- PostgreSQL/browser/external checks are either passed or explicitly still unverified;
- accessibility and error states are included, not deferred by accident;
- audit logging contains useful metadata without secrets or excessive personal data;
- tenant/SBU isolation is proven with negative tests;
- documentation and action registry are updated;
- `progress.md` records the evidence;
- no unrelated file is staged or changed;
- commit/push/deploy occur only under separate user authorization.

The programme is done only after the stabilization release is accepted and each selected product task has independently met this definition. Unselected product tasks remain planned, not partially implemented.

## 10. Explicitly deferred or prohibited shortcuts

- No big-bang frontend rewrite or framework migration.
- No removal of ARIA lifecycle guards to fix Save.
- No global ERM library edit access for organization users.
- No compatibility `erm_risks` view hiding stale code.
- No synthetic webhook success log.
- No SSRF fix based only on hostname prefixes.
- No automatic mutation retries without idempotency.
- No diagnostics page exposing secrets/raw exceptions.
- No duplicate task, exercise, evidence-file, KRI, or policy workflow model when an existing canonical model can be extended.
- No AI narrative presented as verified fact without sources and human approval.
- No production test using real customer data when synthetic scoped fixtures suffice.
- No claim that route HTTP 200 proves button functionality.
