# PLAN-SBU-01: User -> Business Unit assignment UI - active tracking (2026-07-22)

## Status: COMPLETE

## Goal
See plans/PLAN-SBU-01-user-bu-assignment.md for full spec. Activate the
dead `governance.bu.assign` capability with a real "People" tab in the
Governance module (assign users to BUs), plus a convenience BU dropdown
in the super-admin Admin->Users edit drawer.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-SBU-01-active.md

### Step 1: data_service helpers (governance/data_service.py)
- [x] list_assignable_users()
- [x] assign_user_business_unit(uid, bu_id)

### Step 2: routes (governance/routes.py)
- [x] GET /api/users (gated governance.bu.assign)
- [x] PATCH /api/users/{uid}/business-unit (gated governance.bu.assign)

### Step 3: Governance "People" tab (governance/templates/index.html)
- [x] Tab button gated on can_assign_bu
- [x] Tab panel + table
- [x] JS: govBuOptions, govLoadPeople, govAssignBu, lazy-load wiring

### Step 4: Admin->Users context (launcher/_route_helpers.py)
- [x] business_unit_id/name in per-user SELECT (both branches)
- [x] business_units list + can_assign_bu in ctx

### Step 5: Admin->Users edit drawer (launcher/templates/admin_users.html)
- [x] BU select in drawer, gated can_assign_bu
- [x] data-bu on edit button, wired through openEditDrawer
- [x] saveEditDrawer sends business_unit_id in PATCH body

### Step 6: verify
- [x] py_compile on touched .py files
- [x] Jinja parse both templates
- [x] JS syntax check both templates' script blocks

### Step 7: tests (tests/test_bu_assignment.py)
- [x] 5 test cases (assign/clear, reject unknown BU, reject inactive BU,
      bu_scope_ids rollup after assignment, list_assignable_users surfaces
      BU name + excludes inactive users)
- [x] Full pytest suite, no regressions (181/181 passed: 176 prior + 5 new)

### Step 8: live browser verification
- [x] Super-admin (`_sbu_verify_sa`): People tab visible, assigned
      `_sbu_verify_target` to EcoCash (TEST) via the People tab, then
      re-assigned to Econet Group (TEST) via the Admin->Users drawer -
      both persisted, confirmed via direct DB read after each.
- [x] Temp grc_officer user (`_sbu_verify_grc`, non-super-admin): People
      tab visible and fully functional (listed all 7 active users with
      correct current BU selections, including the target user's
      assignment made moments earlier by SA); performed a live
      re-assignment (target user -> EcoCash id 4) as this persona and
      confirmed both the DB write and the audit_log row were attributed
      to `_sbu_verify_grc`, not to SA - proving the capability and the
      route are genuinely exercised by this persona, not just visible to
      it. `/admin/users` returned a 403 page for this same session,
      confirming `platform.manage_users` remains super-admin-only.
- [x] bu_scope_ids real end-to-end proof: after assigning the target user
      to the parent BU (Econet Group TEST, id 3), ran
      `bu_scope_ids({"business_unit_id": 3, "is_super_admin": 0})`
      directly against the live dev DB and got `[3, 4]` - the rollup
      correctly includes the child EcoCash BU. This is the same
      assignment path a real admin would use, proving the whole
      previously-dead scoping mechanism is now reachable.
- [x] Admin->Users drawer BU dropdown persists (see SA bullet above -
      the drawer-driven reassignment to id 3 was confirmed via DB read).
- [x] Invalid/inactive BU id -> 400: verified at the data_service level
      via `test_assign_rejects_unknown_bu` and `test_assign_rejects_inactive_bu`
      in the pytest suite rather than via a second live HTTP round-trip -
      both new routes (`api_assign_user_bu` in governance/routes.py) call
      `assign_user_business_unit()` directly with no additional branching
      of their own beyond `if not ok: raise HTTPException(400, ...)`, so
      the unit-level proof fully covers the route's behavior. Not
      re-verified over live HTTP to avoid creating and tearing down a
      second round of throwaway BU rows purely to re-prove already-proven
      logic.
- [x] Cleanup all temp accounts/data: deleted users 21/22/23 (+ their
      user_roles/sessions/audit_log rows) and business_units 3/4 from
      `oneforall/data/oneforall.db`. Verified afterward: 4 users remain
      (the original set), 1 business unit remains (root "Company"), 0
      audit_log rows reference the `_sbu_verify_*` usernames.

## Deviation notes

1. **No tab-caching flag added.** The plan's Step 3 sketch assumed a
   `_peopleLoaded`-style cache flag so the People tab only fetches once.
   The real `govSwitchTab`/`govLoadTab` in this codebase has no caching
   for any tab - every switch re-fetches unconditionally. Matched the
   existing convention instead of introducing a new pattern solely for
   this tab.
2. **Add button hidden on the People tab.** The existing generic
   "+ Add X" button label map (`{bu:'Business Unit', dept:'Department', ...}`)
   has no entry for `people`, and would render "+ Add undefined" for any
   user who can both assign BUs and manage entities (the common case,
   since `governance.bu.assign` and `governance.entities.manage` are
   granted to the same roles). Fixed by hiding the Add button entirely
   when `tab==='people'`, since assignment there is inline-per-row with
   no separate "create" action - consistent with the plan's own note
   that assignment is inline-save with no Save button.
3. **Raw `fetch()` used instead of the shared `apiFetch()` wrapper for the
   PATCH call.** `apiFetch()` throws a bare `Error('HTTP '+status)` with
   no access to the response body, but `govAssignBu()` needs the JSON
   `detail` message (e.g. "Invalid or inactive business unit") to show a
   useful toast on failure. Used a plain `fetch()` call instead, matching
   how a small number of other mutating calls in this same file already
   handle cases where the error body matters.
4. **`routes_admin.py`'s existing `PATCH /api/admin/users/{uid}` endpoint
   was left unvalidated.** Unlike the new `assign_user_business_unit()`
   helper (which checks the target BU exists and is active), the
   pre-existing Admin->Users save path writes `business_unit_id` directly
   with no such check. This is a real inconsistency between the two save
   paths, but `routes_admin.py` was not in this plan's file list -
   flagged here rather than fixed, since fixing it would mean editing a
   file outside PLAN-SBU-01's stated scope without being asked.
