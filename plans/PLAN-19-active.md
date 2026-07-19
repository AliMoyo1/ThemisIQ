# PLAN-19: RoPA/DPIA Integration — active tracking (2026-07-17)

## Status: COMPLETE (2026-07-17)

## Goal

Link RoPA and DPIA records bidirectionally, prefill DPIA from RoPA,
show drift when the source RoPA changes after the DPIA was last edited.

## What already existed (no rebuild needed)

- `spawn-dpia` endpoint at `/api/ropa/{ropa_id}/spawn-dpia`: creates DPIA from
  RoPA fields, updates `sentinel_ropa.dpia_id`. Missing: 409 guard and
  `ropa_id` on the DPIA row.
- `snSpawnDpia` JS at line 1558 of index.html: calls spawn-dpia, navigates to
  dpia tab.
- DPIA list "Linked RoPA" column already renders `d.ropa_name`, always shows
  dash since JOIN is missing.
- DPIA form uses `special_cats` (not `special_categories`) confirmed at line
  2184 of index.html.

## Changes log

### Step 1: Create active plan file
- [x] plans/PLAN-19-active.md

### Step 2: DB migration
- [x] database.py: add `("sentinel_dpias", "ropa_id", "INTEGER")` to _COLUMN_MIGRATIONS
- [x] database.py: add `("sentinel_ropa", "risk_level", "TEXT DEFAULT 'low'")` to _COLUMN_MIGRATIONS (dev DB schema gap fix, discovered during live verification)

### Step 3: Data service
- [x] sentinel/data_service.py - update delete_dpia to clear sentinel_ropa.dpia_id
- [x] sentinel/data_service.py - add link_dpia_to_ropa() with backfill-only semantics
- [x] sentinel/data_service.py - fix: map ropa.purpose to dpia.activity_desc (not "description") in _RPA_TO_DPIA
- [x] sentinel/data_service.py - update list_dpias with LEFT JOIN ropa for ropa_ref/ropa_name/ropa_updated_at
- [x] sentinel/data_service.py - update get_dpia with same JOIN

### Step 4: Routes
- [x] sentinel/routes.py - update spawn-dpia: add 409 guard + set ropa_id on DPIA + special_cats mapping
- [x] sentinel/routes.py - add POST /api/dpias/{dpia_id}/link-ropa

### Step 5: UI
- [x] index.html - snSpawnDpia: handle 409, open DPIA drawer on success
- [x] index.html - DPIA basics tab: add Linked RoPA dropdown + link-ropa call
- [x] index.html - DPIA list: render ropa_ref as chip
- [x] index.html - DPIA drawer: drift banner when ropa_updated_at > updated_at

### Step 6: Tests
- [x] tests/test_ropa_dpia_link.py (5 test cases: prefill+link, second spawn refused, backfill only, delete clears link, list JOIN fields)
- [x] full pytest: 119/119 pass

### Step 7: Update README
- [x] plans/README.md

## Live verification results (2026-07-17)

- RoPA POST: OK (id=1, risk_level migrated correctly)
- spawn-dpia from RoPA id=1: OK (DPIA-20260717-8H1RG, all fields prefilled, ropa_id=1)
- second spawn on same RoPA: 409 "This activity already has a linked DPIA."
- link-ropa on standalone DPIA: OK (200, backfilled department/activity_desc/legal_basis, enriched with ropa_ref/ropa_name)
- 119/119 tests pass

## Key constraints (from PLAN-19)

- Backfill never overwrites non-empty DPIA fields. Empty = NULL or '' after strip.
- DPIA form uses special_cats, not special_categories.
- Deleting a DPIA must clear sentinel_ropa.dpia_id.
- 409 on second spawn must produce a visible toast and chip flip.
- Drift comparison is string-based lexicographic (no date parsing).
- Ref number via existing _gen_ref helper only.
