# PLAN: pooled connection returned dirty by tenant provisioning and migration

Status in this tree (2026-10-08): implemented and verified on real PostgreSQL 18.6 as part of the integration of the parallel chats; see PLAN_integrate_parallel_chat_changes.md, step 1. The text below is the original plan from the chat that wrote it, kept as the record of the defect and the design.

Date: 2026-10-07. Branch: claude/amazing-brattain-42ceb5. Status: INCOMPLETE (stopped at a usage limit). Nothing committed or pushed.

## Goal
`provision_tenant_schema()` and `_migrate_all_tenant_schemas()` in `oneforall/database.py` must hand their pool connection back clean, so a bare `get_db()` never inherits `app.bypass_rls='true'` or a tenant `search_path`.

## Defect (confirmed by reading the code; runtime proof still to do)
- Both functions take a raw pool connection, call `wrapper.set_rls_bypass()` and set `search_path` to a tenant schema.
- `_apply_tenant_schema_ddl()` commits (database.py around lines 6559 and 6565), so those session-level SETs become committed state.
- Their `finally` blocks only `rollback()` and `putconn()`. They never call `_clear_rls_context()`, which only `_PgConnWrapper.close()` runs.
- `get_db()` applies scope only when a tenant or org is bound, and the pool is LIFO (POSTGRES_POOL_MIN defaults to 2), so the dirty connection is the first one reused.
- `_migrate_all_tenant_schemas()` only dirties the connection when at least one tenant schema exists. With none it never commits, so the final rollback undoes the bypass SETs. The test therefore provisions one first.
- Observed on a real PostgreSQL 18.6 by the user (same backend pid, search_path 'tenant_contamorg, public', bypass_rls 'true').

## Fix (NOT applied yet, by design: prove first)
In both functions replace the `finally` body with `wrapper.close()`. `close()` already does rollback, resets search_path and the three app.* settings, commits the reset, and putconn (or a hard close if the reset fails). Keep the `_is_alive` / `putconn(close=True)` startup logic.
File: `oneforall/database.py`, the `finally:` blocks near lines 6740 (provision) and 6799 (migrate).

## Test (drafted, never run)
`oneforall/tests/test_postgres_init.py`: a helper that spies on `pool.getconn` to record the backend pid of the connection under test, then opens a bare `get_db()` and reads pg_backend_pid(), search_path, app.bypass_rls, app.current_org_id and app.is_super_admin. The pid equality assertion keeps the test from being vacuous. Assertions are on settings, not RLS row filtering, because the lane's postgres user is a superuser.

## How to run the PG lane
1. Start Docker Desktop if the daemon is down. The postgres:18 image is already cached; do not pull.
2. `docker run -d --name themisiq-pg-test-contam -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=themisiq_test_contam -p 127.0.0.1:55432:5432 postgres:18`
3. Environment: `THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1` and `TEST_DATABASE_URL=postgresql://postgres:pg@127.0.0.1:55432/themisiq_test_contam`
4. From `oneforall/`, with the repo venv: `C:\Projects\One For All\One For All\.venv\Scripts\python.exe -m pytest tests/test_postgres_init.py -v`
5. Full suite (about 9.5 minutes) with the same interpreter, from `oneforall/`. One pytest session at a time.
6. Remove the container when done.

## Change log
- [done] Created this plan file.
- [done, not run] `oneforall/tests/test_postgres_init.py`: added `_bare_session_after`, `_assert_pool_connection_is_clean`, `test_provision_tenant_schema_returns_a_clean_connection_to_the_pool`, `test_migrate_all_tenant_schemas_returns_a_clean_connection_to_the_pool`.
- [todo] Run the two new tests against real PG and confirm they FAIL before the fix. Record the pids and settings seen.
- [todo] Apply the fix in `oneforall/database.py`.
- [todo] Re-run the two tests (expect pass), then the whole PG lane, then the full suite with the repo venv.
- [todo] Report what ran and what could not run.
