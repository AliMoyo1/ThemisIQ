# PLAN-33: User Management v2 (SBU grouping, delete, bulk Excel import)

## Status: PHASES 1-3 COMPLETE (Phase 1 verified live 2026-07-23; Phases 2-3
## implemented and verified live 2026-07-23 per "start phase 2 and 3").
## Phase 4 (bulk row actions) not started -- optional, no follow-up
## instruction yet.

## Phase 2 implementation notes

- `database.py`: added `("users", "deleted_at", "TEXT")` to
  `_COLUMN_MIGRATIONS` (applies on both SQLite and Postgres via the existing
  `_run_sqlite_alters`/`_run_pg_alters` idiom) plus an
  `idx_users_deleted_at` index.
- `routes_admin.py`: `_USER_REFERENCE_TABLES` + `_user_reference_counts(db,
  uid)` -- a best-effort (not exhaustive) map of the schema's known
  user-referencing columns (audit_log, erm_enterprise_risks, task_board,
  business_units/departments.head_user_id, calendar_events,
  workflow_instances, email_reminders, evidence_items), used by both the
  new `GET /admin/api/users/{uid}/impact` preview endpoint and the
  hard-delete safety gate. New routes: `POST /admin/users/{uid}/delete`
  (soft delete -- sets `deleted_at` + `is_active=0`, clears sessions, same
  self/last-active-admin guardrails as deactivate), `POST
  /admin/users/{uid}/restore` (clears `deleted_at` only -- does NOT
  reactivate, an explicit Reactivate is still required), `POST
  /admin/users/{uid}/hard-delete` (permanent row delete, refuses with a
  clear message if `_user_reference_counts` finds anything, falls back to
  "use Delete (safe) instead").
- `_route_helpers.py`: `_render_admin_users` reads `?show_deleted=1` from
  the query string and conditionally excludes `deleted_at IS NOT NULL`
  rows; `_group_users_by_bu` and the org-grouping loop both track a new
  `deleted_count` separate from `active_count`/`inactive_count`. Headline
  stats (`stat_total`/`stat_active`/`stat_inactive`/`stat_pw_pending`)
  always exclude deleted users regardless of the toggle, so turning it on
  doesn't skew them; a separate `stat_deleted` count feeds the toggle's
  badge.
- `admin_users.html`: "Show Deleted (N)" toggle chip in the toolbar
  (reloads with/without `?show_deleted=1`); a `.b-deleted` status badge and
  dimmed `.au-row-deleted` row style; actions cell branches to
  Restore + Delete Permanently for deleted rows, or the existing actions
  plus a new Delete button (with a best-effort impact-preview `confirm()`
  fetched from the impact endpoint) for normal rows.
- Verified live: soft-delete hid the user and dropped the header count;
  Show Deleted revealed it with the Deleted badge + Restore/Delete
  Permanently actions; Restore cleared `deleted_at` but correctly left
  `is_active=0`; hard-delete on a zero-reference user fully removed the row
  and its `user_roles`; hard-delete on a user with one `audit_log` row was
  correctly refused with "Cannot permanently delete ...: still referenced
  by 1 audit log entries. Use Delete (safe) instead." 6 new tests in
  `tests/test_user_delete.py`, 200/200 full suite passing.

## Phase 3 implementation notes

- New `modules/launcher/_user_import.py`, mirroring the ERM risk-register
  importer's two-phase shape: `parse_users_excel(file_bytes, is_super,
  caller_org_id)` (preview) and `bulk_create_users(rows, admin,
  bu_overrides, org_overrides)` (commit). Fuzzy-matches the Business Unit
  column via `difflib.get_close_matches` against `business_units`,
  validates emails, auto-derives usernames from full name when blank
  (with a numeric-suffix collision fallback), validates role keys against
  `ALL_ROLES` (dropping unrecognized ones and stripping `super_admin`
  for non-super callers, both surfaced as warnings), flags duplicate
  emails against both the existing `users` table and other rows in the
  same sheet.
- **Bug found and fixed during testing**: `_norm_header` did not strip
  parenthetical hints ("Username (optional)", "Roles (comma-separated)")
  before normalizing, so the *template this module itself generates*
  failed to match its own `_HEADER_MAP` -- those two columns silently
  fell through unmapped on every import. Fixed by stripping `(...)` before
  normalizing. Caught by `test_parse_users_excel_drops_unrecognized_and_super_admin_roles`
  expecting a warning that never appeared.
  `bulk_create_users` org-scopes exactly like PLAN-30: a non-super caller's
  rows are always forced into their own `org_id`, ignoring any
  `organization_raw`/override; a super-admin caller may target any org
  fuzzy-matched from an Organization column, or an explicit override.
  Temp passwords are generated per row (`must_change_password=1`) and
  returned once in a `credentials` list for admin handoff -- never
  persisted anywhere else. Per-row `try/except` (with `db.rollback()` on
  failure) so one bad row doesn't abort the batch.
- `routes_admin.py`: `GET /admin/api/users/template` (downloadable `.xlsx`
  with the expected headers + one example row + two reference sheets:
  "Valid Business Units", "Valid Roles"), `GET /admin/api/users/export`
  (CSV of current non-deleted users, org-scoped, doubles as a seat-usage
  report), `POST /admin/api/users/import-preview` (multipart upload -> the
  parser's preview payload), `POST /admin/api/users/import-commit` (JSON
  body `{rows, bu_overrides, org_overrides}` -> the commit result).
- `admin_users.html`: Export / Template / Import Excel buttons next to New
  User; a `#userImportResult` banner; `showUserImportPreview()` renders a
  modal (summary stat cards, BU-mapping table with confidence badges,
  sample-rows table) mirroring the ERM import modal's structure;
  `commitUserImport()` posts the commit and renders a credentials handoff
  table (username + one-time temp password per created user) plus a
  "Done -- Refresh List" button (deliberately not an auto-reload, so the
  admin has time to copy the passwords before the page refreshes).
- Verified live end-to-end over real HTTP (not just the unit tests):
  uploaded a real 2-row `.xlsx` (one exact-match BU, one fuzzy-typo'd BU,
  one multi-role row) to `/admin/api/users/import-preview`, confirmed the
  fuzzy match ("Verify-SBU-Typo" -> "Verify SBU") and role parsing were
  correct, rendered the real preview modal from that real response
  (screenshotted), clicked through to a real commit, and confirmed both
  users were created in the DB with the correct `business_unit_id`,
  `org_id`, roles, and `must_change_password=1`. Also verified `/template`
  returns a valid non-empty `.xlsx` and `/export` returns a well-formed CSV
  reflecting live DB state (correctly excluding deleted/hard-deleted temp
  users). 8 new tests in `tests/test_user_import.py`, 200/200 full suite
  passing.

## Phase 1 implementation notes

- `_route_helpers.py`: new `_group_users_by_bu()` helper buckets a list of
  user rows by `business_unit_id` (named BUs alphabetically, "Org-wide (no
  unit)" always last). `_render_admin_users` now also fetches
  `bu_parent_names` (a one-query self-join over `business_units`) and
  attaches `bu_groups` to each org in `orgs_grouped` (super-admin view) and
  as a top-level `bu_groups` for the single-org view.
- `admin_users.html`: new `bu_grouped_table(bu_groups)` macro replaces the
  flat per-user loop in BOTH the super-admin (nested inside each org) and
  org-admin (top-level) branches, so every viewer gets the SBU grouping.
  Each BU header shows its name, "under <parent>" when nested, and
  active/inactive/pw-pending counts -- click to collapse. Added a Business
  Unit filter dropdown (works in both views) and extended `filterUsers()`
  to filter by `data-bu-id` and hide/auto-expand `.bu-section` alongside
  the existing `.org-section` logic. Removed the now-dead flat-table
  (`#usersTable`) empty-state JS, since neither view has a single flat
  table anymore -- both share `#filterEmptyHost`.
- Verified live: super-admin view showed Test Econet -> Ecocash/Econet/
  OmniContact (each correctly labeled "under Econet") + Org-wide, Test Org
  B -> Org-wide, and the real accounts correctly separate under
  "Unassigned". The org_admin persona's view showed only their own 6 users,
  same BU grouping, no org-selector (correctly is_super-gated away). The
  BU filter dropdown correctly isolated OmniContact's 2 users and hid every
  other BU section. 186/186 tests pass, no regressions. All temp orgs/BUs/
  users cleaned up afterward.

## Context

Post-consolidation, Econet Group is one tenant with SBUs modeled as
`business_units` (OmniContact / Ecocash / Econet Wireless under the Econet
root, plus the Company root). The Admin -> User Management page
(`modules/launcher/_route_helpers.py::_render_admin_users` +
`templates/admin_users.html`) currently groups users only by ORGANIZATION
(super-admin view). The user wants it to also group by SBU within the tenant,
add real user deletion, and add bulk user creation from Excel optimized for
the SBU/parent-company structure.

Existing building blocks to reuse (do not rebuild):
- Every user row already carries `business_unit_id` + `business_unit_name`
  (added in PLAN-SBU-01's `_render_admin_users`).
- The two-phase Excel preview/commit pattern already exists for risks
  (`parse_risk_register_excel` / `bulk_import_risks` in erm/data_service.py,
  `/erm/api/risks/import-preview` + `import-commit`, preview modal in
  erm/index.html). The user importer mirrors this shape.
- Bulk-select UI precedent exists (Task Board bulk operations).
- Deactivate + guardrails (last-admin, self) already exist in routes_admin.py.

## Feature 1 -- Group users by SBU under their tenant company

Turn the flat per-org user list into a two-level tree: **Organization ->
Business Unit -> users**, with an "Org-wide (no unit)" bucket for users whose
`business_unit_id` is NULL.

- **Backend** (`_render_admin_users`): after building `orgs_grouped`, add a
  second grouping pass that buckets each org's users by `business_unit_id`
  (ordered by BU name, "Org-wide" last), attaching per-BU counts
  (active / inactive / pw-pending). Pass the BU tree so groups can show the
  parent->child relationship (e.g. indent SBUs under their parent BU).
- **Frontend** (`admin_users.html`): render org header -> collapsible BU
  sub-headers (name, code, active/total counts) -> user rows. Reuse the
  existing collapse mechanism. Keep the flat search working across all groups.
- **Complements** (cheap, include here):
  - A **Business Unit filter** dropdown alongside the existing role/org
    filters ("show only OmniContact").
  - **Per-SBU seat counts** in each BU header.

## Feature 2 -- Delete users

**Design decision required (this platform is a GRC/compliance system, so
audit-trail integrity matters):** a user is referenced across many tables
(`audit_log.user_id`, `created_by`, `owner_id`, `granted_by`, ...). A blind
hard DELETE would either violate FKs or orphan/erase audit history -- which is
exactly what an auditor would flag.

Recommended model ("safe delete"):
- **Default = soft delete + hide.** Add a `deleted_at` timestamp (or reuse a
  status). Deleted users vanish from the normal list (a "Show deleted" toggle
  reveals them), their sessions are cleared, and they cannot log in. Audit
  history and ownership references stay intact and attributable. Reversible.
- **Hard delete only when safe.** Offer a true row-delete ONLY when the user
  has zero references (e.g. a just-created mistake) -- the endpoint checks the
  referencing tables first and refuses (or falls back to soft delete) if any
  exist. Optionally an "anonymize" variant (scrub PII, keep the row) for GDPR
  erasure requests.
- Same guardrails as deactivate: cannot delete yourself, cannot delete the
  last active admin in an org, super-admin-role grant/revoke still gated.
- A small **impact preview** ("this user owns 4 risks, 2 audits -- reassign or
  proceed?") before deletion, so the admin sees consequences.

Alternatives the user may prefer instead: pure hard-delete with
`ON DELETE SET NULL` migrations on the FKs (simpler UI, permanent, loses
attribution) -- called out so the user can choose. **This is the one decision
that gates implementation.**

## Feature 3 -- Bulk create users from Excel (SBU + parent-company aware)

Mirror the risk-register importer's two-phase flow.

- **Template**: a downloadable `.xlsx` with headers and one example row, plus
  reference sheets listing the tenant's valid Business Unit names and role
  keys, so imports don't fail on typos. Columns:
  `Full Name | Email | Username (optional) | Roles (comma-sep) | Business Unit (SBU) | Organization (super-admin only)`.
- **Parse + preview** (`parse_users_excel`): fuzzy-match the Business Unit
  column to existing BUs (same `difflib` approach the risk importer uses for
  categories), validate emails, auto-derive usernames when blank, flag
  duplicates (against existing users AND within the sheet), validate role
  keys. Preview modal shows: summary counts, BU match table (editable
  dropdowns), role validation, warnings, sample rows -- exactly like the risk
  preview.
- **Commit** (`bulk_create_users`): create each user in the target org with
  the resolved `business_unit_id` + roles, generate a one-time temp password
  (`must_change_password=1`), wrap per-row so one bad row doesn't kill the
  batch. Returns created count + the temp-password handoff list (shown once,
  and/or exported).
- Org scoping: an ORG_ADMIN import is forced into their own org (reuse
  PLAN-30's org-scoping); a super-admin may target any org via the
  Organization column.

## Additional suggestions (my proposals, layered in)

1. **Export users to Excel/CSV** -- round-trips with the importer; also a
   ready-made seat-usage-per-SBU report. Cheap once the importer's column
   model exists.
2. **Bulk row actions** -- multi-select users -> assign BU / deactivate /
   grant role in one go. This is the feature that would have made the manual
   SBU reshuffle we just did a single click. Extends the Task Board bulk
   pattern.
3. **Downloadable import template with live BU/role reference sheets** (folded
   into Feature 3 above).
4. **Per-SBU seat/pending indicators** in group headers (folded into
   Feature 1).
5. **Invitation-email onboarding** (send a set-password link instead of a
   temp password) -- nicer, but needs the email pipeline; defer to a later
   slice.
6. **User "impact / ownership" drawer** -- what a user owns across modules
   (supports the delete impact preview and general oversight); medium effort.

## Proposed implementation order

1. **Phase 1 (foundational): SBU grouping + BU filter + per-SBU counts.**
   Makes the page navigable; unlocks the rest.
2. **Phase 2: Delete users** (per the chosen semantics) + impact preview.
3. **Phase 3: Bulk Excel import + downloadable template + Export.**
4. **Phase 4 (optional): Bulk row actions.**
5. **Later: invitation email flow.**

## Open decisions for the user

- **Delete semantics**: safe-delete (soft + hide, reversible, audit-preserving)
  [recommended] vs. permanent hard-delete with FK SET NULL.
- **Where to build**: the standing dev-workflow note says build/verify in the
  ThemisIQ-dev repo first, then promote to master. Given production just took
  a crash from a Postgres-only path the SQLite tests could not exercise,
  dev-first is the safer call for this UI-heavy work -- confirm.
- **Priority/scope**: all four phases, or a subset first?

## Verification approach (per phase)

`py_compile` + Jinja parse + JS `node --check` on touched templates + full
pytest + new tests for the importer/delete data-service functions + a live
browser pass (local preview) creating/importing/deleting temp users in temp
SBUs, then cleanup. No commit to production until each phase's acceptance
criteria pass.
