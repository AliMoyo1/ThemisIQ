# PLAN-18 Parts B+C: Active tracking file (2026-07-16)

## Goal

Part B: SBU data scoping - enforce users.business_unit_id filtering so BU-assigned users
only see their BU (and descendants) rows plus NULL-BU shared rows.

Part C: Upload magic-byte verification - reject files whose byte content does not match
their declared extension.

## Status: COMPLETE (2026-07-16)

## Changes log

### Step 1: Add business_unit_id to session user dict
- [x] core/auth.py - add u.business_unit_id to SELECT in get_session_user + returned dict

### Step 2: Add bu_scope_ids helper
- [x] modules/governance/data_service.py - add bu_scope_ids(user) -> list | None

### Step 3: Add bu_scope parameter to list functions
- [x] modules/erm/data_service.py - list_enterprise_risks: add bu_scope param
- [x] modules/grid/data_service.py - list_audits: add bu_scope param
- [x] modules/sentinel/data_service.py - list_ropa, list_dpias, list_breaches: add bu_scope param
- [x] modules/bcm/data_service.py - list_bia, list_plans: add bu_scope param
- [x] modules/orm/data_service.py - list_events: add bu_scope param

### Step 4: Inject scope + detail guards in route handlers
- [x] modules/erm/routes.py - inject scope in list route, add detail guard
- [x] modules/grid/routes.py - inject scope in list route, add detail guard
- [x] modules/sentinel/routes.py - inject scope in ropa/dpia/breach list routes + detail guards
- [x] modules/bcm/routes.py - inject scope in plans/bia list routes + detail guards
- [x] modules/orm/routes.py - inject scope in events list route + detail guard

### Step 5: User BU assignment in admin
- [x] modules/launcher/routes_admin.py - add business_unit_id to PATCH /api/admin/users/{uid}

### Step 6: Part C - upload magic-byte check
- [x] modules/evidence/routes.py:
  - Add .html, .htm, .svg, .xhtml to blocked_extensions
  - Remove text/html, image/svg+xml from allowed_mimes
  - Add _MAGIC table (module-level constant)
  - Add magic-byte check after content = await file.read()

### Step 7: Verify
- [x] py_compile all touched files: ALL OK
- [x] pytest full suite: 114/114 passed

### Step 8: Update README
- [x] plans/README.md - updated with current plan statuses

## Key constraint: OR business_unit_id IS NULL

Every BU scope filter must be:
  AND (business_unit_id IN (%s,...) OR business_unit_id IS NULL)
NOT just:
  AND business_unit_id IN (%s,...)
The second form hides all pre-existing NULL-BU (shared) records from every BU-assigned user.

## Key constraint: 404 not 403 for detail out-of-scope

The detail endpoint guard must return 404, not 403.
403 confirms the record exists (IDOR oracle).
