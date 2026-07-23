# PLAN-30: Org Admin role + three-tier Settings navigation — active tracking (2026-07-23)

## Status: COMPLETE

## Goal
See plans/PLAN-30-org-admin-role-and-settings-tiering.md for full spec.
New tenant-scoped `org_admin` role + `platform.manage_org_users` capability,
reusing the existing-but-unreachable org-scoping logic in `_target_user`/
`_render_admin_users`, closing the SUPER_ADMIN grant/revoke escalation gap,
and building the three-tier settings nav (Super Admin / Org Admin /
Governance Settings).

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-30-active.md

### Step 1: core/rbac.py — new role + capability
- [x] ORG_ADMIN role constant + ALL_ROLES + ROLE_LABELS + ROLE_DESCRIPTIONS + ROLE_MODULE + ROLE_CHIP_TONE
- [x] platform.manage_org_users capability
- [x] ORG_ADMIN added to governance.entities.manage + governance.bu.assign

### Step 2: routes_admin.py
- [x] 2a: widen decorator on 8 routes to accept platform.manage_org_users
- [x] 2b: block non-super-admin grant/revoke of SUPER_ADMIN role

### Step 3: admin_users.html — filter grant dropdown
- [x] super_admin option hidden unless is_super

### Step 4: core/shell_context.py — new context flags
- [x] can_org_admin
- [x] can_governance_settings

### Step 5: base_shell.html — new nav icons
- [x] Org Admin icon (amber)
- [x] Governance Settings icon (violet)

### Step 6: platform_base.html — Org Admin sidebar section
- [x] elif can_org_admin branch (User Management + Org Structure)

### Step 7: tests/test_org_admin.py (new)
- [x] 4 test cases, all passing

### Step 8: verify
- [x] py_compile touched .py files (core/rbac.py, core/shell_context.py, modules/launcher/routes_admin.py, tests/test_org_admin.py)
- [x] Jinja parse touched templates (base_shell.html, admin_users.html, platform_base.html)
- [x] Full pytest suite: 185/185 passed (181 prior + 4 new)
- [x] Live browser: super admin (`_p30_super`) unaffected — still only grey "Admin"
      cog, sees both PLAN30 Org A and Org B in the org filter, grant dropdown
      still offers "Super Administrator"
- [x] Live browser: org_admin (`_p30_orgadmin`, Org A) — rail shows exactly one
      amber "Org Admin" icon, no grey cog, no violet Governance Settings.
      `/admin/users` lists only Org A's 4 users (Org B's `_p30_emp_b` correctly
      absent). Grant dropdown does not offer "Super Administrator" anywhere.
      Direct `POST /admin/users/29/roles/grant` with `role_key=super_admin`
      rejected with the new error message (confirmed via fetch(), not just
      UI absence). Direct `POST /admin/users/30/deactivate` (Org B's user)
      rejected "User not found" and DB-confirmed `is_active` unchanged.
      `/admin/api-keys` still 403s. `/governance/` reachable, "+ Add Business
      Unit" visible (governance.entities.manage granted), successfully
      assigned Org A's `_p30_emp_a` to the "Company" BU via the People tab,
      confirmed in DB and correctly audit-logged as actor `_p30_orgadmin`.
- [x] Live browser: grc_officer (`_p30_grc`) — rail shows exactly one violet
      "Governance Settings" icon (no Org Admin, no Admin cog).
      `/admin/users` still returns 403 (capability set unchanged for this role).
- [x] Cleanup: deleted users 27-31, their user_roles/sessions/audit_log rows,
      and both temp organizations. Verified after: 4 users, 0 organizations
      (dev DB's baseline state), 0 audit_log rows referencing `_p30_*`.

## Deviation notes

1. **Found during verification, not introduced by this plan, not fixed
   here**: the Governance module's "People" tab (`list_assignable_users()`
   in `modules/governance/data_service.py`, shipped in PLAN-SBU-01) has no
   `org_id` filter at all — it lists **every active user across every
   organization** on the whole platform, and lets whoever is viewing it
   reassign any of their business units. This was already true before
   PLAN-30 (any `GRC_OFFICER`/`COMPLIANCE_MGR` could already do this), but
   PLAN-30 makes it more load-bearing: `ORG_ADMIN` is specifically supposed
   to be "manages users... within their own organisation only," and this
   is a second, wide-open path to cross-org data for exactly that role.
   Confirmed live: `_p30_orgadmin` (Org A) saw and could reassign
   `_p30_emp_b` (Org B) via the People tab, despite the `/admin/users` path
   correctly refusing the same action. Out of PLAN-30's stated file list
   (`modules/governance/data_service.py` was never named in the spec) —
   flagged to the user rather than silently fixed. The natural fix mirrors
   `_target_user`'s exact pattern: filter `list_assignable_users()` by the
   caller's `org_id` unless they hold `platform.manage_users`
   (true super admin).
2. **`admin_revoke_role`'s pre-existing "last admin" safety check already
   imports `SUPER_ADMIN` locally** (for its "don't strip the last admin in
   this org" logic) — the new escalation guard added its own
   `from core.rbac import SUPER_ADMIN` immediately after the CSRF check,
   ahead of that existing one. Both imports coexist harmlessly (redundant,
   not conflicting); not worth removing the older one just to deduplicate.

### Follow-up fix: People tab org-scoping (same session, user-approved)

Deviation note 1 above was fixed immediately after being flagged, per
explicit user instruction ("fix the People tab and commit both"):

- `modules/governance/data_service.py`: `list_assignable_users()` gained an
  optional `caller` parameter. When the caller is not a super admin, adds
  `AND u.org_id = %s` scoped to the caller's own `org_id` — mirrors
  `_target_user`'s exact pattern. No caller (back-compat) or a true super
  admin still sees every active user platform-wide, matching the function's
  original behavior.
- `modules/governance/routes.py`: `api_assignable_users` now passes
  `request.state.user` through. `api_assign_user_bu` (the PATCH endpoint)
  gained an explicit IDOR guard — for non-super callers, looks up the
  target's `org_id` and raises `404 "User not found"` before ever calling
  `assign_user_business_unit()` if it doesn't match the caller's own org.
  This closes a second path to the same gap: even after the list is
  filtered, a caller who already knew or guessed another org's `uid` could
  otherwise still PATCH it directly.
- `tests/test_bu_assignment.py`: added
  `test_list_assignable_users_scopes_by_org_unless_super_admin` (3 cases:
  non-super caller sees only their org, super admin still sees everyone,
  no-caller back-compat still sees everyone). 6/6 passing in this file,
  190/190 in the full suite.
- Live-verified with a fresh pair of temp orgs/accounts: the People tab for
  a temp Org Admin now shows only their own 2 org users (previously showed
  all 9 platform-wide users including three different orgs' worth). A
  direct `PATCH /governance/api/users/{other-org-uid}/business-unit` was
  rejected with 404 and confirmed via direct DB read to have made zero
  change to the target's `business_unit_id`. All temp orgs/accounts cleaned
  up afterward (back to 4 users, 0 organizations).
