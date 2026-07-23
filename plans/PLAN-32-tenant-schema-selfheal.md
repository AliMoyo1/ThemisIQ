# PLAN-32: Self-heal tenant-schema migration drift

## Status: IMPLEMENTED (code); awaiting live deploy + verification on the VPS.

## Problem

PLAN-31's recon (superuser on the real 5434 DB) found the per-tenant schemas
badly behind: `public` had 173 tables, while `tenant_omni` / `tenant_ecocash`
/ `tenant_econet_wireless` had only ~127 and no `business_units` table at all.

Root cause: `init_db()` applies new tables + `_COLUMN_MIGRATIONS` only to the
`public` schema on startup. Existing tenant schemas got their full structure
once, at `provision_tenant_schema()` time, and were never revisited. So every
table or column added to the canonical definitions after a tenant was
provisioned silently failed to reach that tenant. New tenants are fine
(they provision from the current definitions); existing ones drift.

## Fix (database.py) -- self-healing on startup

1. **Extracted** the idempotent DDL block from `provision_tenant_schema()`
   into `_apply_tenant_schema_ddl(conn)` (create module tables, run
   `_run_pg_alters`, `_run_pg_fk_cascades`, seed baseline). Both provisioning
   and migration now apply the exact same canonical structure.
2. **Added `_migrate_all_tenant_schemas()`**: discovers every `tenant_*`
   schema via `information_schema.schemata`, sets `search_path` to each, and
   replays `_apply_tenant_schema_ddl`. Fully idempotent (CREATE TABLE IF NOT
   EXISTS / ADD COLUMN IF NOT EXISTS / count-gated seeds). Per-schema failures
   are caught, logged, and skipped so one bad tenant can never block startup.
3. **Hooked into `init_db()`** (Postgres branch only), after the public
   migrations + RLS policies, wrapped in its own try/except so the whole pass
   is non-fatal to startup.

Because it runs on every startup and is idempotent, it both fixes the 3
currently-stale (now inactive) schemas on the next restart AND prevents this
drift from ever recurring: any future migration added to the canonical
definitions reaches all existing tenants on the next deploy, not just public.

## Why no unit test

The whole path is gated on `settings.is_postgres()`; the test suite runs on
SQLite (no schemas), so it's inert there -- confirmed the full suite still
passes (186) with no regressions and database.py compiles. Verification is
live on the VPS (below), consistent with how other PG-schema-specific behavior
in this codebase is checked.

## Deploy + verify (VPS, one command per step)

1. `git pull`
2. `sudo systemctl restart themisiq-app`  (init_db runs on startup -> the
   migrate-all pass fires against all tenant schemas)
3. `curl http://localhost:8080/health`
4. Re-run the recon and confirm the 3 tenant schemas now report ~173 tables
   and a `business_units` table (they were ~127 and had none):
   `sudo -u postgres python3 oneforall/scripts/econet_migration_recon.py > /project/recon_after.txt`
   then `grep -n "schema:" /project/recon_after.txt` and spot-check the
   tenant table counts.

## Notes / tradeoffs

- Runs the idempotent DDL for every tenant schema on every startup. Cheap at
  this scale (a handful of tenants); if the tenant count grows large, a
  version-guard (skip schemas already at the current version) can be added.
  Not needed now.
- The 3 target schemas belong to now-inactive orgs (post PLAN-31
  consolidation). Bringing them current is still worthwhile: it makes them
  safe to reactivate and makes any future data-copy job (the deferred Omni
  Option C) straightforward, since source and target schemas would match.
