# PLAN-33: User Management v2 (SBU grouping, delete, bulk Excel import)

## Status: PHASE 1 COMPLETE (verified live 2026-07-23). User decisions:
## delete = safe delete (soft-delete + hide, reversible) when Phase 2 is
## built; build directly on master; scope was Phase 1 ONLY (SBU grouping +
## BU filter + seat counts). Phases 2-4 not started -- awaiting a
## follow-up instruction to proceed.

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
