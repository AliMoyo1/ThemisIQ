# PG session state lost on rollback: prove, fix, regression-test

**Suspected defect (found by code reading, not yet reproduced):**
`database.py` `get_db()` (PostgreSQL branch) applies the tenant `search_path` and the
RLS settings (`app.current_org_id`, `app.is_super_admin`, `app.bypass_rls`) with plain
session-level `SET`. PostgreSQL rolls a `SET` back with the transaction it was issued in.
Nothing commits them, so they sit in the connection's first open transaction.
`_PgConnWrapper.execute()` rolls the whole transaction back on any exception, which
silently reverts the connection to its previous session values. A caller that catches the
exception and keeps using the same `db` then runs against the default `public` schema with
no tenant or RLS scope.

**Goal:** prove it on a real PostgreSQL 18, fix it once at the root, lock it in with
regression tests, run the full suite with the repo venv.

## Environment

- Real PG lane: `oneforall/tests/test_postgres_init.py` (`pg` fixture, destructive-test guard).
- Container: `themisiq-pg-test-session-state`, image `postgres:18` (already cached locally,
  no pull), database `themisiq_test_session_state`, bound to 127.0.0.1:55432 only.
- Env for the lane: `THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1` and `TEST_DATABASE_URL`.
- Interpreter: `C:\Projects\One For All\One For All\.venv\Scripts\python.exe` (global Python
  silently skips `tests/ui`).

## Files to touch

- `oneforall/tests/test_postgres_init.py` (failing tests first, then keep as regression tests)
- `oneforall/database.py` (`_PgConnWrapper`, the single shared place; fix once)

## Approach

1. Write failing real-PG tests first (get_db tenant scope, explicit rollback, bypass
   connection, mid-flight `set_tenant` rebind). Run them red against the unmodified code.
2. Choose the smaller correct fix between: commit right after the SETs, or re-apply the
   context after rollback. Decide on evidence from step 1, not on reading alone.
3. Re-run the new tests green; confirm `close()` reset path, `get_db_bypass_rls`,
   `provision_tenant_schema` are unaffected.
4. Audit other call sites that catch a DB error and keep using the same connection.
5. Full suite with the venv; report what ran and what could not run.

## Out of scope (report only, do not fix here)

Anything found along the way that is not this defect is recorded under "Adjacent findings"
below and reported to the user instead of being changed.

## Change Log

- [done] Docker Desktop started; `postgres:18` already cached; throwaway container up, PG 18.6 ready.
- [done] `oneforall/tests/test_postgres_init.py`: added 5 real-PG tests (+ `import psycopg2.errors`):
  get_db scope vs failed statement, vs explicit rollback, bypass connection, `_bind_target_org`
  rebind, and a `close()` clean-return guard.
- [done] RED run on unmodified `database.py`: 4 failed, 1 passed (the guard). Observed on PG 18.6,
  same backend pid before and after the failed statement: `search_path`
  `tenant_x, public` -> `public`, `app.current_org_id` `'1'` -> `''`, `app.bypass_rls`
  `true` -> `false`, `app.is_super_admin` `true` -> `false`. Data impact (scratch probe): the
  connection read `public.sla_definitions` instead of the tenant's, and a write after the
  failure landed in `public`.
- [done] `oneforall/database.py` `_PgConnWrapper.set_tenant/set_rls_context/set_rls_bypass`:
  each now commits right after its SETs (docstrings explain why). `get_db()`,
  `get_db_bypass_rls()`, `_bind_target_org`, `close()` unchanged.
- [done] GREEN: whole real-PG lane 20 passed (15 pre-existing + 5 new).
- [done] `oneforall/tests/test_infrastructure_reliability.py`: added
  `test_postgres_scope_setters_commit_so_a_rollback_cannot_undo_them` (fake raw connection,
  runs in the default SQLite suite). Verified it FAILS against the old setters and passes now.
- [done] `oneforall/database.py` `set_tenant` docstring: added the warning that the commit also
  commits work already pending, so scope must be bound before writing.
- [done] Cost measured on the throwaway PG (statement log): one scoped get_db()+query+close()
  is 13 statements before, 17 after (+4: a COMMIT and a BEGIN per setter). Timing here
  10.5 ms -> 13.3 ms per cycle through Docker Desktop networking, so only the ratio transfers.
  Unscoped connections are unchanged.
- [done] Call-site audit (AST heuristic, scratch): 58 try/except sites in modules and core that
  catch a DB error and keep using the connection (55 swallow, 3 explicit rollback), 21 files,
  worst: `modules/launcher/routes_dashboard.py` (14, widgets wrapped in
  `except Exception: pass  # tables may not exist`). The root fix covers all of them; none edited.

## Design decision (setter-level commit)

Rejected: commit only in `get_db()` (leaves `get_db_bypass_rls()` and the `_bind_target_org`
mid-flight rebind exposed, proven by tests 3 and 4); re-apply inside `execute()` only (an
explicit `db.rollback()` in the caller's `except` would undo the re-applied SETs, so
`rollback()` would need hooking too, plus remembered-state bookkeeping). The three setters are
the only writers of scope, so committing there covers every caller at once. All four runtime
`_bind_target_org` calls are the first DB work after `get_db()`, so no pending caller writes
are committed early.

## Adjacent findings (reported, not changed)

- Savepoint call sites are broken on PG: `modules/readiness/data_service.py:115-122` and
  `modules/saved_views/data_service.py:254-261`. `execute()` rolls the whole transaction back
  on the inner failure, so the later `ROLLBACK TO SAVEPOINT` raises
  `InvalidSavepointSpecification` and earlier uncommitted work in the transaction is lost.
- Dirty pool return: `provision_tenant_schema()` and `_migrate_all_tenant_schemas()` end with
  `pg_conn.rollback(); pool.putconn(pg_conn)`, never `_clear_rls_context()`. Observed: the next
  unscoped `get_db()` got the same backend with `app.bypass_rls = 'true'` and a tenant
  `search_path`.

## Final verification

- Full suite, repo venv, from `oneforall/`, PG lane enabled: 1321 passed, 2 skipped, exit 0,
  26m49s. The 2 skips are unrelated UI fixtures (`tests/ui/test_action_registry_http_contracts.py:89`,
  `tests/ui/test_chip_filters_are_buttons.py:90`). The suite started before the final
  docstring-only edit to `set_tenant`; that edit was py_compile-checked and the lane was not
  re-run after it.
- Not run: anything against a non-superuser application role (the lane's `postgres` user
  bypasses RLS, so RLS row filtering is not exercised by the new tests); the production VPS.
- Two follow-up tasks queued as chips (not done here): dirty pool return after provisioning,
  and savepoint call sites vs the wrapper's whole-transaction rollback.
- Throwaway container removed. Docker Desktop left running.
- Nothing committed or pushed. Changes are uncommitted in this worktree.

## Status: COMPLETE (pending your review and go-ahead to commit)
