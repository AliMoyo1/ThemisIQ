# PLAN: Fix tenant provisioning FK failure (applications.vendor_id)

## Problem
`oneforall/database.py` defines the `applications` table twice (in `_SHARED_TABLES` and `_PLATFORM_TABLES`), both with:

    vendor_id INTEGER REFERENCES canonical_vendors(id) ON DELETE SET NULL,

`canonical_vendors` is created later in `_GRID_TABLES`. On PostgreSQL, `provision_tenant_schema` runs `_PLATFORM_TABLES_PG` before `_GRID_TABLES_PG`, so the REFERENCES clause points at a table that does not exist yet and provisioning fails mid-schema.

## Fix
Change both occurrences (lines 1110 and 1603) to a bare `vendor_id INTEGER,` (app-level integrity, matching the cross_module_links precedent in the same file).

## Steps
- [x] Edit line 1110 (_SHARED_TABLES applications)
- [x] Edit line 1603 (_PLATFORM_TABLES applications)
- [x] python -m py_compile oneforall/database.py
- [x] Run full pytest suite in oneforall/tests/
- [x] Fresh-database smoke test: init_db() against a temp SQLite path, confirm applications table creates
- [x] Commit: "Fix tenant provisioning: applications.vendor_id FK referenced a table created later"

## Log
- 2026-07-08: Replaced both `vendor_id INTEGER REFERENCES canonical_vendors(id) ON DELETE SET NULL,` lines (1110 in _SHARED_TABLES, 1603 in _PLATFORM_TABLES) with bare `vendor_id INTEGER,`. Vendor linkage integrity is now app-level, same as cross_module_links.
- 2026-07-08: py_compile passed. Full pytest suite in oneforall/tests/ passed (77 tests, 0 failures).
- 2026-07-08: Fresh SQLite smoke test passed: init_db() on a temp path created the applications table with vendor_id column present. Two pre-existing "Skipped index" warnings for erm_risks on fresh DBs are unrelated to this change.
