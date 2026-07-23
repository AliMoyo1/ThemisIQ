# PLAN-30: Org Admin role + three-tier Settings navigation

## Status: SPEC ONLY — not yet implemented. Do not start without an explicit instruction to implement this plan.

## Goal

Today there is no tenant-scoped user-management role. `platform.manage_users`
(the capability behind the "Admin Settings" cog — Users & Roles, API Keys,
Webhooks, Connectors, Audit Log, Security, Email Settings) is granted to
`SUPER_ADMIN` only, and `SUPER_ADMIN` is a *platform-wide* role — a super
admin manages users across every tenant, not just one. There is no way for a
customer's own designated admin to manage their own org's users without
handing them full platform-wide super-admin power (every other tenant's data,
API keys, webhooks, security settings, the lot).

This plan adds a new **Organization Administrator** role, scoped strictly to
the caller's own tenant, and reorganizes the Settings-style icons in the nav
rail into three clean, non-overlapping tiers:

1. **Super Admin** (existing, unchanged) — full platform-wide access: every
   org, every user, API keys, webhooks, connectors, security, email settings,
   plus Org Structure.
2. **Org Admin** (new) — manages users, roles, and password resets *within
   their own org only*, plus Org Structure. Cannot see or touch any other
   tenant, cannot grant/revoke the `super_admin` role, cannot reach API Keys /
   Webhooks / Connectors / Security / Email Settings.
3. **GRC Officer / Compliance Manager** (existing capability, new icon) — Org
   Structure only (business units, departments, people/BU-assignment). No
   user-account management at all.

Each user sees **exactly one** of these three icons (or none, for roles like
Employee/Auditor that hold none of the underlying capabilities) — never two
overlapping ones for the same destination.

## Why this is safer than it looks: most of the hard part already exists

`modules/launcher/routes_admin.py` already has a `_target_user(db, uid, admin)`
helper (line 27) that scopes every mutating user-admin action to the caller's
own `org_id` unless the caller is a true super admin, and `_render_admin_users`
(`modules/launcher/_route_helpers.py:67`) already renders an org-scoped user
list (not the cross-org grouped view) whenever the caller isn't a super admin.
This logic was clearly written anticipating exactly this role and has simply
never been reachable, because every route in that file is gated
`@_require_cap("platform.manage_users")` = `{SUPER_ADMIN}` only. This plan's
core job is: (a) add a second, narrower capability that reaches the *user*
routes only, (b) close the one real privilege-escalation gap that opens up
once a non-super-admin can reach them (granting/revoking `super_admin`
itself), and (c) build the nav tier for it.

## Step 1 — `core/rbac.py`: new role + capability

Add after `GRC_OFFICER = "grc_officer"` (line 26):
```python
ORG_ADMIN = "org_admin"  # tenant-scoped user administrator
```

Add to `ALL_ROLES` (line 28-33), anywhere in the list (position doesn't
matter — it's not ordered by privilege):
```python
ORG_ADMIN,
```

Add to `ROLE_LABELS` (after line 51):
```python
ORG_ADMIN: "Organization Administrator",
```

Add to `ROLE_DESCRIPTIONS` (after line 71):
```python
ORG_ADMIN: "Manages users, roles, and password resets within their own "
           "organisation only. Cannot access other tenants or "
           "platform-wide settings (API keys, webhooks, security).",
```

Add to `ROLE_MODULE` (after line 91):
```python
ORG_ADMIN: "platform",
```

Add to `ROLE_CHIP_TONE` (after line 111). Use `"warn"` (amber), not `"bad"`
(red, reserved for `SUPER_ADMIN`) — this role is elevated but explicitly
*not* full-privilege, and the badge color should say so at a glance:
```python
ORG_ADMIN: "warn",
```

Add a new capability next to `platform.manage_users` (line 119). Keep
`platform.manage_users` itself untouched (still `{SUPER_ADMIN}` only, still
gates API Keys/Webhooks/Connectors/Security/Email Settings/the cross-org
view) — this is a **separate, narrower** capability that reaches only the
`/admin/users*` route family:
```python
"platform.manage_org_users":  {SUPER_ADMIN, ORG_ADMIN},
```

Add `ORG_ADMIN` to the two existing governance capability grant sets (line
130-131), since assigning your own org's users to a business unit is a
natural extension of "managing my org's users" — this is exactly what
motivated this whole plan:
```python
"governance.entities.manage": {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, RISK_OWNER, ORG_ADMIN},
"governance.bu.assign":       {SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR, ORG_ADMIN},
```

Do **not** add `ORG_ADMIN` to `platform.manage_users`, `platform.manage_settings`,
or any `module.*.access` capability. It should default to the same module
access as `EMPLOYEE` unless the org grants it more roles separately (an org
admin is an admin function bolted onto whatever their day-to-day role
already is — granting `ORG_ADMIN` doesn't imply they should see ARIA/GRID/
BCM/Sentinel/ERM/ORM content they otherwise wouldn't).

## Step 2 — `modules/launcher/routes_admin.py`: widen the gate, close the one real gap

**2a. Widen the decorator** on exactly these 8 routes (the entire
`/admin/users*` + `/api/admin/users/{uid}` family — nothing else in this
file) from `@_require_cap("platform.manage_users")` to
`@_require_cap("platform.manage_users", "platform.manage_org_users")`
(`require_capability`/`_require_cap` already accepts multiple capabilities
and requires *any one* of them — `core/middleware.py:66-83` — so this is a
one-argument addition, not new logic):
- `GET /admin/users` (line 66-69)
- `POST /admin/users/create` (line 72-73)
- `POST /admin/users/{uid}/roles/grant` (line 149-150)
- `POST /admin/users/{uid}/roles/revoke` (line 182-183)
- `POST /admin/users/{uid}/deactivate` (line 237-238)
- `POST /admin/users/{uid}/activate` (line 283-284)
- `POST /admin/users/{uid}/reset-password` (line 307-308)
- `PATCH /api/admin/users/{uid}` (line 340-341)

Do **not** touch the decorators on any other route in this file (audit logs,
API keys, webhooks, connectors, security, email settings all stay
`platform.manage_users`-only, i.e. true super admin only).

**2b. Close the privilege-escalation gap** — this is the one change that
isn't already handled by existing code. In `admin_grant_role`
(line 149-179), immediately after the `role_key not in ALL_ROLES` check
(line 159-161), add:
```python
from core.rbac import SUPER_ADMIN
if role_key == SUPER_ADMIN and not admin.get("is_super_admin"):
    return _render_admin_users(request, admin,
        {"type": "error", "message": "Only a super administrator can grant the Super Administrator role."})
```
Add the exact same guard to `admin_revoke_role` (line 182-234), immediately
after the CSRF check (line 188-190), before the existing `_target_user` call:
```python
if role_key == SUPER_ADMIN and not admin.get("is_super_admin"):
    return _render_admin_users(request, admin,
        {"type": "error", "message": "Only a super administrator can revoke the Super Administrator role."})
```
(`admin_revoke_role` already imports `SUPER_ADMIN` locally at line 199 for
its "last admin" check — reuse that import, don't duplicate it; just make
sure the new guard runs before that existing block, not after.)

Without this, `_target_user`'s org scoping only restricts **which user** an
Org Admin can act on — it says nothing about **which role** they can grant
that user. An Org Admin could otherwise grant `super_admin` to any user in
their own org (or to themselves, since nothing stops self-targeting on
grant), which is full platform-wide privilege escalation from a role that is
supposed to be tenant-scoped. This is the single most important line in this
entire plan — do not skip it.

**Explicit design decision, not a gap**: this plan deliberately does **not**
block an Org Admin from granting or revoking the `ORG_ADMIN` role itself to
other users in their own org. An org's admin should be able to deputize a
colleague as a second org admin without waiting on a platform super admin.
Only `SUPER_ADMIN` is special-cased.

## Step 3 — `modules/launcher/templates/admin_users.html`: hide what the backend now blocks

The role-grant dropdown (lines 419-425) currently lists every role in
`all_roles` (which includes `SUPER_ADMIN`) with no filtering — offering an
option that Step 2b's backend guard will reject is confusing, not just
insecure-looking. Filter it:
```html
<select name="role_key" onchange="this.form.submit()"
        class="role-add-select" aria-label="Grant role">
  <option value="" disabled selected>+ grant…</option>
  {% for rk in all_roles %}{% if rk not in u.role_keys and (is_super or rk != 'super_admin') %}
    <option value="{{ rk }}">{{ role_labels.get(rk, rk) }}</option>
  {% endif %}{% endfor %}
</select>
```
(`is_super` is already in this template's context — set in
`_render_admin_users`, `_route_helpers.py:70` — no new context var needed.)

Leave the revoke chips (lines 394-408) and the Role Reference legend (lines
585-603) unchanged — an Org Admin seeing that a user in their org happens to
hold `super_admin` (if a platform admin was seeded into their org) with a
disabled-looking revoke is fine; the backend guard in 2b is what actually
matters, and hiding the *chip* would make it harder to understand why a
grant/revoke silently didn't change anything. Only the dropdown that lets
you newly assign it needs filtering.

## Step 4 — `core/shell_context.py`: two new context flags

Add to the dict returned by `shell_ctx()` (after line 83's
`"can_governance_view"` entry):
```python
"can_org_admin": has_capability(user, "platform.manage_org_users") and not has_capability(user, "platform.manage_users"),
"can_governance_settings": has_capability(user, "governance.bu.assign")
    and not has_capability(user, "platform.manage_users")
    and not has_capability(user, "platform.manage_org_users"),
```
The `and not ...` guards are what make the three tiers mutually exclusive —
a true super admin still only sees the existing "Admin Settings" cog (which
already includes Org Structure per the prior commit), not a second
redundant "Org Admin" icon; an Org Admin sees "Org Admin" but not a third
redundant "Governance Settings" icon since Org Structure is already reachable
from their own settings icon.

## Step 5 — `templates/base_shell.html`: new "Org Admin" icon

In the `icon-sidebar-bottom` block, immediately after the existing
`{% if is_admin %}...{% endif %}` "Admin Settings" block (currently lines
707-713), add a new mutually-exclusive block:
```html
{% if can_org_admin %}
<a href="/admin/users" class="icon-nav-item{% if active_section in ('admin','users') %} active{% endif %}" title="Org Admin" style="color:#d97706">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15 1.65 1.65 0 003.17 14H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68 1.65 1.65 0 0010 3.17V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
  <span class="icon-nav-tooltip">Org Admin — your organisation's users</span>
  <span class="nav-label">Org Admin</span>
</a>
{% endif %}
```
Same cog glyph as "Admin Settings" (it's conceptually the same action —
manage users — just org-scoped), but a distinct amber (`#d97706`) instead of
the muted grey used for the super-admin version, and a distinct label so
the two are never confused.

Add a second new block for GRC Officer / Compliance Manager, right after
that one:
```html
{% if can_governance_settings %}
<a href="/governance/" class="icon-nav-item{% if active_module == 'governance' %} active{% endif %}" title="Governance Settings" style="color:#6d28d9">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M6 21V10M18 21V10M9 21V14h6v7M3 10l9-6 9 6"/></svg>
  <span class="icon-nav-tooltip">Governance Settings — Business Units &amp; Entities</span>
  <span class="nav-label">Governance Settings</span>
</a>
{% endif %}
```
Reuses the same building icon and violet (`#6d28d9`) already used for Org
Structure elsewhere, since it's the same destination.

## Step 6 — `modules/launcher/templates/platform_base.html`: Org Admin's own sidebar section

The `{% if is_admin %}` block (lines 73-98) is the full super-admin cluster
(User Management, API Keys, Webhooks, Connectors, Audit Log, Security) — do
not add Org Admin to that condition, or they'd get everything. Instead add a
parallel `{% elif can_org_admin %}` branch right after it closes (after line
98's `{% endif %}`, still inside the same `<div class="sidebar-section">` at
line 59-99):
```html
{% if is_admin %}
  ... (existing 6 links, unchanged) ...
{% elif can_org_admin %}
  <a href="/admin/users" class="nav-item{% if active_section == 'users' %} active{% endif %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
    User Management
  </a>
  <a href="/governance/" class="nav-item{% if active_section == 'org_structure' %} active{% endif %}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M6 21V10M18 21V10M9 21V14h6v7M3 10l9-6 9 6"/></svg>
    Org Structure
  </a>
{% endif %}
```
Note this template's own `{% if is_admin %}...{% endif %}` currently ends
with the "Org Structure" link added in the previous commit (inside the
super-admin branch) — that stays; this step only adds the sibling `{% elif %}`
branch for the narrower Org Admin case.

## Step 7 — `oneforall/tests/test_org_admin.py` (new file)

Cover, using the standard `test_db` fixture and the `_create_user` helper
pattern from `test_bu_assignment.py`:
1. **Cross-org isolation**: create two orgs, one user in each, an
   `org_admin` in org A. Call `_target_user(db, user_in_org_b_id, org_admin_user)`
   directly — assert it returns `None` (not found), proving the org filter
   in `_target_user` (already-existing code) actually engages for this new
   role now that it's reachable.
2. **Same-org access works**: `_target_user(db, user_in_org_a_id, org_admin_user)`
   returns the row.
3. **`platform.manage_org_users` capability check**: `has_capability({"is_super_admin":0,"..."}, "platform.manage_org_users")`
   is `True` for a user holding the `org_admin` role, `False` for `employee`.
4. **`platform.manage_users` is unaffected**: `has_capability(org_admin_user, "platform.manage_users")`
   is `False` — confirms Org Admin still cannot reach API Keys/Webhooks/
   Connectors/Security/Email Settings (those routes are untouched, still
   gated on the un-widened capability).
5. Import `admin_grant_role`'s guard logic can't be unit-tested in isolation
   easily since it's a FastAPI route function reading `request.state.user` —
   cover this one via the live-browser pass instead (Step 8), not a unit
   test, matching how other route-level guards in this codebase are
   verified.

## Step 8 — Verification

1. `python -m py_compile` on `core/rbac.py`, `core/shell_context.py`,
   `modules/launcher/routes_admin.py`.
2. Jinja parse `templates/base_shell.html`,
   `modules/launcher/templates/admin_users.html`,
   `modules/launcher/templates/platform_base.html`.
3. Full `pytest` suite — confirm no regressions, plus the new
   `test_org_admin.py` cases pass.
4. Live browser pass, two temporary orgs (or reuse two of the existing
   4 seeded orgs if convenient), three temp accounts:
   - Temp super admin: confirm nothing changed for them — still one
     "Admin Settings" cog, still sees every org's users, grant dropdown
     still offers every role including Super Administrator.
   - Temp `org_admin` in Org A: confirm the rail shows exactly one new
     icon labeled "Org Admin" (amber), not the grey "Admin Settings" cog,
     not a separate "Governance Settings" icon. Click it → lands on
     `/admin/users` showing **only Org A's users** (no org grouping, no
     "All Organizations" filter, matching the existing `is_super`-gated
     template branches). Confirm a user that exists only in Org B is not
     listed and a direct `POST /admin/users/{org_b_uid}/deactivate` (or any
     other mutating action) returns "User not found" via `_target_user`'s
     existing org filter. Confirm the "+ grant…" dropdown does **not**
     list "Super Administrator" as an option. Confirm a raw POST to
     `/admin/users/{uid}/roles/grant` with `role_key=super_admin` is
     rejected with the new error message from Step 2b, not silently
     applied. Confirm creating a new user via this account lands them in
     Org A regardless of any tampering (the existing `admin_create_user`
     logic at `routes_admin.py:93` already forces this for non-super
     callers — just needs re-confirming now that a non-super role can
     reach the endpoint). Confirm clicking "Org Structure" style access
     (via `/governance/`, reachable since `ORG_ADMIN` now holds
     `governance.bu.assign`) works and lets them assign an Org-A user to a
     business unit.
   - Temp `grc_officer` (or `compliance_manager`): confirm the rail shows
     exactly one icon labeled "Governance Settings" (violet), and that
     `/admin/users` still 403s for them (their capability set didn't
     change — only the nav/UI changed for the org_admin persona, not this
     one).
5. Clean up all temp orgs/accounts afterward, matching this session's
   standing convention.

## Edge cases a weaker model would miss

- **The privilege-escalation gap (Step 2b) is the load-bearing part of this
  plan.** Widening the decorator (Step 2a) alone, without Step 2b, ships a
  real vulnerability: any Org Admin could grant themselves or anyone in
  their org the `super_admin` role and immediately have full platform-wide
  access to every tenant. Do not ship 2a without 2b in the same change.
- **`_target_user` already does the org-scoping — do not re-implement it.**
  It's tempting to add a fresh org check inside each of the 8 routes; don't.
  They already call `_target_user(db, uid, admin)` and it already returns
  `None` for cross-org targets when `admin.get("is_super_admin")` is falsy.
  Re-adding the check would be redundant at best and risks a second,
  slightly different implementation drifting out of sync with the first.
- **`admin_create_user`'s org-forcing logic (line 93) already works** for
  any non-super caller — it doesn't check role, just `is_super_admin`. No
  change needed there at all; it was already correct, just unreachable.
- **Mutual exclusivity of the three nav icons is deliberate**, not an
  oversight to "simplify later." A user who is both a true super admin and
  also happens to hold the `org_admin` role (unusual, but not prevented by
  this plan) should still see only the one, most-privileged "Admin
  Settings" icon — the `can_org_admin` flag's `and not has_capability(...,
  "platform.manage_users")` guard in Step 4 is what prevents a confusing
  second icon in that case.
- **Do not touch `platform.manage_users` itself.** It's tempting to just
  add `ORG_ADMIN` to that one capability's set and skip creating
  `platform.manage_org_users` entirely — don't. That capability also gates
  API Keys, Webhooks, Connectors, Security, and Email Settings routes in
  this same file, none of which an Org Admin should reach.
- **The "last super admin" safety checks in `admin_revoke_role` (line
  198-212) and `admin_deactivate_user` (line 255-271) scope their count by
  the *target's* `org_id`**, not globally. This is pre-existing behavior,
  not something this plan changes — but it's worth knowing that if a
  platform super admin happens to be the only `super_admin`-tagged user
  within a given org's `org_id`, that specific safety check will fire for
  anyone (including another super admin) trying to revoke/deactivate them.
  Orthogonal to this plan; do not "fix" it as a drive-by.
- **`admin_users.html`'s revoke chips and Role Reference legend are left
  unfiltered on purpose** (Step 3) — only the *grant* dropdown needs
  filtering, because the backend guard (2b) is what actually prevents harm;
  hiding existing role chips would just make an Org Admin's screen more
  confusing about why a user has a role they can't remove.
- **Test via `_target_user` directly, not by trying to unit-test the route
  functions.** These are FastAPI path operation functions reading
  `request.state.user` and returning `_render_admin_users(...)` — properly
  unit-testing them requires a real request/response cycle. The existing
  test suite's pattern for this kind of thing is to test the underlying
  helper directly and cover the route-level behavior in the live-browser
  pass (Step 8), not to write a FastAPI TestClient integration test that
  doesn't otherwise exist in this codebase's test suite.

## Acceptance criteria (what "done" looks like)

1. A brand-new `org_admin` role exists, with its own label, description,
   badge color, and the `platform.manage_org_users` capability.
2. Logging in as an `org_admin` user shows exactly one settings-style icon
   ("Org Admin", amber), landing on an org-scoped `/admin/users` view (their
   org's users only, no cross-org UI).
3. That user can create/deactivate/reactivate/reset-password/edit-profile/
   grant-non-super-roles for users **within their own org only** — any
   attempt (via UI or direct request) to act on a user in a different org
   fails with "User not found."
4. That user **cannot** grant or revoke the `super_admin` role under any
   circumstance, and the UI doesn't even offer it as a grant option.
5. That user **cannot** reach `/admin/api-keys`, `/admin/webhooks`,
   `/admin/connectors`, `/admin/security`, `/admin/email`, or `/admin/logs`
   (still 403 — `platform.manage_users` untouched).
6. That user **can** reach `/governance/` and assign their own org's users
   to business units (via the existing PLAN-SBU-01 People tab and/or the
   Admin→Users edit-drawer BU dropdown).
7. A true super admin's experience is pixel-identical to today — one "Admin
   Settings" icon, full cross-org access, every role grantable.
8. A GRC Officer / Compliance Manager sees exactly one icon ("Governance
   Settings", violet) leading straight to Org Structure, and still cannot
   reach `/admin/users` at all.
9. Full pytest suite green, including the new `test_org_admin.py` cases.
10. No commit until these are all verified live and the user explicitly
    signs off — matching this session's standing rule.
