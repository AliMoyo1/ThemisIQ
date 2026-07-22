# PLAN: My Dashboard role-detection bug

## Goal

`GET /api/my-dashboard/data` (oneforall/modules/launcher/routes_dashboard.py,
`api_my_dashboard_data()`) does `role = user.get("role", "employee")`, but the
user dict from `core/auth.py`'s `get_session_user()` has no singular `role`
key, only `roles` (a list of role_key strings from `user_roles`). Every user
silently falls back to `"employee"`, so the role-specific widget branches
(super_admin/compliance_mgr, audit_lead/auditor, dpo/privacy_analyst,
bcm_manager/incident_commander/bcm_responder, policy_author/policy_approver/
control_owner/risk_owner) are dead code. Confirmed live: a test account with
role_key='compliance_manager' got `{"role": "employee", ...}` back with none
of the compliance_mgr fields.

## Files to touch

- `oneforall/modules/launcher/routes_dashboard.py`

## Findings during investigation

1. **Primary bug (assigned task):** `role = user.get("role", "employee")` at
   line 590, should derive from `user["roles"]` (list) instead.
2. **Entangled dead-code bug:** the `role in ("super_admin", "compliance_mgr")`
   branch (which is currently unreachable) references `org_filter`/`org_arg`,
   which are never defined in `api_my_dashboard_data()`. They only exist in
   the *other* function above it (`api_command_centre_stats`). Fixing bug #1
   alone would make this branch reachable and immediately crash with
   `NameError` for super_admin/compliance_manager/grc_officer users.
3. **Wrong role-key string:** the branch checks `"compliance_mgr"`, but
   `core/rbac.py` defines `COMPLIANCE_MGR = "compliance_manager"`. This
   string could never have matched even after fixing bug #1. Also `GRC_OFFICER`
   ("grc_officer") is not handled by any branch despite holding nearly the
   same cross-module capability set as compliance_manager/super_admin in
   `rbac.CAPABILITIES` (aria/grid/bcm/sentinel/erm access, missing only orm).
4. **Same-file, uncommitted sibling fix found in the main repo** (not this
   worktree, `C:\Projects\One For All\One For All`, branch master, working
   tree, not committed): a different session already fixed a closely related
   NameError. `api_command_centre_stats` reads `user.get("is_super_admin")` /
   `user.get("org_id")` without `user` ever being assigned in that function
   (a live bug, would 500 on every Command Centre stats load). Their fix
   extracts a small `_org_scope_filter(user)` helper and uses it in both
   `api_command_centre_stats` AND in `api_my_dashboard_data`'s
   super_admin/compliance_mgr branch (i.e. they already independently hit and
   fixed bug #2 above, defensively, even though the branch was unreachable at
   the time). This worktree does not have that uncommitted fix (worktrees
   don't share working-tree state). Mirroring their exact approach here so
   this branch doesn't ship a known-and-already-solved crash, and so the two
   lines of work reconcile cleanly later.
   - NOT fixing `api_command_centre_stats`'s missing `user =
     request.state.user` would be out of scope for this task (unrelated to
     role detection), except that it's part of the same small, already-verified
     diff that introduces `_org_scope_filter`, which I do need for bug #2.
     Replicating the whole small diff rather than half of it avoids inventing
     a second, divergent version of the same helper.

## Approach (product decision: multi-role handling)

A user's `roles` is a list (can hold multiple role_keys) but the branching
logic assumes one string. Going with **option (a): priority-ordered primary
role** rather than (b) merge-all-matching-branches, because:
- Zero frontend changes required. `my_dashboard.html` already expects a
  single `role` string for both display AND client-side widget gating
  (`WIDGET_CATALOG`, `widgetsForRole()`, `widgetQuickLinks()` all key off one
  role value using the same, currently-dead role strings). Merging branches
  on the backend would return richer data but the frontend would still only
  render ONE role's widget set, silently dropping the rest: a bigger,
  separate frontend rework (multi-role-aware widget catalog plus merged quick
  links) that's out of scope for this bug fix.
- (a) is a strict improvement over the current 100%-broken state for every
  user, with no risk of half-implemented merge behavior.
- Flagging (b) as a legitimate follow-up if the user wants multi-role users
  to see combined widgets. That would need `my_dashboard.html`'s
  `WIDGET_CATALOG`/`widgetsForRole`/`widgetQuickLinks` reworked to be
  roles-aware (intersection instead of single-value match), not just a
  backend change.

Priority order (judgment call, ordered by breadth of platform access per
`rbac.ROLE_DESCRIPTIONS`; only matters for users holding >1 role_key):
super_admin > grc_officer > compliance_manager > dpo > bcm_manager >
audit_lead > risk_owner > incident_commander > bcm_responder > auditor >
privacy_analyst > policy_approver > policy_author > control_owner >
external_auditor > employee.

## Log

- [done] routes_dashboard.py: added `_org_scope_filter(user)` helper after
  `my_dashboard()`; added `user = request.state.user` to
  `api_command_centre_stats`; replaced its inline org_filter/org_arg
  computation with a call to the helper.
- [done] routes_dashboard.py: added `_DASHBOARD_ROLE_PRIORITY` constant above
  `api_my_dashboard_data()`.
- [done] routes_dashboard.py:601-605ish: `role` now derived from
  `user.get("roles")` (set) via the priority list, falling back to
  `"employee"` only if the user holds no recognised role_key.
- [done] routes_dashboard.py: fixed `"compliance_mgr"` to `"compliance_manager"`
  in the branch condition, added `"grc_officer"` (matches its near-identical
  cross-module capability set in rbac.CAPABILITIES vs. compliance_manager).
  Added `org_filter, org_arg = _org_scope_filter(user)` inside that branch
  right before the query that needs them (branch is now actually reachable).
- [done] py_compile check: pass.
- [done] Compared all other elif tuples (audit_lead/auditor,
  dpo/privacy_analyst, bcm_manager/incident_commander/bcm_responder,
  policy_author/policy_approver/control_owner/risk_owner) against
  rbac.py's role_key constants: all already correct, no changes needed.
- [done] templates/my_dashboard.html: found the frontend has the exact same
  `'compliance_mgr'` string baked into `WIDGET_CATALOG` (compliance_overview,
  module_health, recent_activity) and `widgetQuickLinks()`'s admin-context
  check. Without fixing these too, the backend fix alone would still show no
  widgets for compliance_manager/grc_officer (frontend role-string mismatch,
  same bug, client side). Fixed all 4 occurrences: `'compliance_mgr'` to
  `'compliance_manager'`, plus added `'grc_officer'` to each list/array to
  match the backend branch decision.
- [done] Live verification via dev server + browser:
  - Seeded fresh local SQLite DB (`python seeds/seed.py`, DEBUG=true via a
    temporary local `.env`, removed afterwards). Creates admin (super_admin),
    compliance (compliance_manager + audit_lead), dpo (dpo), bcm (bcm_manager).
  - Ran the app via the existing "AegisGRC" launch config (had to temporarily
    add `autoPort`/`%PORT%` to this worktree's `.claude/launch.json` since
    port 8080 was already held by another session's server; reverted both
    changes after testing, confirmed via `git status`/`git diff` that
    `.claude/launch.json` is back to its original tracked state).
  - Logged in as `compliance` (roles: compliance_manager + audit_lead):
    `/api/my-dashboard/data` returned `role: "compliance_manager"`,
    `role_label: "Compliance Manager"` (previously always "employee"),
    `aria_controls_total`/`grid_audits_active`/`sentinel_*` fields present,
    and `recent_audit_entries` populated with a real row. This confirms the
    priority pick (compliance_manager over audit_lead), the string fix, and
    the org_filter/org_arg fix all work together with no NameError. Compliance
    Overview, Module Health, and Recent Activity widgets rendered in the
    browser; Quick Access showed the admin-context links. Zero console errors.
  - Logged in as `dpo` (single role: dpo, a branch whose strings I did NOT
    touch): role_label showed "Data Protection Officer" and the Privacy
    Dashboard widget rendered with RoPA/DPIA/DSR/breach counts. Confirms the
    root fix (deriving `role` from `roles`) generalizes correctly beyond the
    one branch I edited.
  - Command Centre (`/`) also loaded correctly with live stats, confirming
    the mirrored `_org_scope_filter`/`user = request.state.user` fix in
    `api_command_centre_stats` works (that endpoint would have 500'd on
    every request without it).
  - Cleaned up: stopped the dev server, removed the temporary `.env`, reverted
    the `.claude/launch.json` port workaround. Left the seeded
    `data/oneforall.db` in place (gitignored, not tracked) since it's a
    reasonable local dev fixture and matches what `git status` showed as
    untouched/untracked before I started.

## Status: COMPLETE, COMMITTED, RECONCILED

All planned changes made, verified live, and committed locally to this
worktree's branch (`claude/goofy-kowalevski-2c4f88`) as `3b90aa8`. Not pushed.

Reconciliation with the other session (see finding #4 above): it finished
and committed its fix to `master` as `ce43a81` ("Fix NameError crashes in
Command Centre stats and My Dashboard endpoints"), independently arriving
at a byte-identical `_org_scope_filter(user)` helper and the same two call
sites. Merged `ce43a81` into this branch (`git merge`, commit `b671f93`):
auto-resolved cleanly with no conflicts, since the overlapping hunks were
textually identical. Verified afterward: `py_compile` passes, no leftover
conflict markers, `grep` confirms `_org_scope_filter` is defined exactly
once and called exactly twice (no duplication), and `git diff a7f5079
b671f93 --stat` shows only the same three files with the same net line
counts as before the merge. This branch is now a strict superset of
master's `ce43a81` plus the role-detection fix and the `my_dashboard.html`
change, both of which master does not yet have.

## Summary

Fixed the reported bug plus two entangled ones, all in
`oneforall/modules/launcher/routes_dashboard.py`:

1. Role detection now reads the user's actual `roles` list instead of a
   nonexistent `role` key that always fell back to `"employee"`.
2. `"compliance_mgr"` to `"compliance_manager"` typo fix, plus added
   `grc_officer` to that branch (dead-string bug: would never have matched
   even after #1).
3. Mirrored a sibling, already-verified, still-uncommitted fix found in the
   main repo (`C:\Projects\One For All\One For All`, not this worktree) for
   an undefined-`user`/undefined-`org_filter` NameError class of bug in this
   same file. Added `_org_scope_filter(user)` helper, used in both
   `api_command_centre_stats` and `api_my_dashboard_data`. Flagged to the user
   to reconcile/dedupe with that other session's commit later.

Not done (explicit follow-up, needs product input): merging dashboard data
across ALL of a user's roles (vs. picking one primary role) would also
require reworking `my_dashboard.html`'s `WIDGET_CATALOG`,
`widgetsForRole()`, and `widgetQuickLinks()` to be roles-aware. Out of scope
for this fix, documented above under "Approach".
