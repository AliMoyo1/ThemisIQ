# PLAN: PostgreSQL savepoints destroyed by _PgConnWrapper.execute()

Status in this tree (2026-10-08): implemented and verified on real PostgreSQL 18.6 as part of the integration of the parallel chats; see PLAN_integrate_parallel_chat_changes.md, step 2. The text below is the original plan from the chat that wrote it, kept as the record of the defect and the design.

Branch: claude/zealous-mcnulty-7b2cde. Status: INVESTIGATED ONLY. No code or test change made yet. Nothing has been run.

## Defect (as reported, proven by the user on real PostgreSQL 18.6)

`_PgConnWrapper.execute()` (oneforall/database.py:259-275) calls `self._conn.rollback()` on ANY exception, then re-raises.
That rolls back the whole transaction, which also destroys any open SAVEPOINT. Two call sites rely on savepoints:

- oneforall/modules/readiness/data_service.py:115-125 (`run_rules_for_org`, savepoint `readiness_rule`)
- oneforall/modules/saved_views/data_service.py:254-262 (`execute_bulk_action`, savepoint `bulk_action_item`)

When a statement inside the savepoint fails, the handler's own `ROLLBACK TO SAVEPOINT` raises
InvalidSavepointSpecification, escapes the except block, and every uncommitted earlier write in that transaction is lost
(findings for earlier rules; items already applied). SQLite never showed this because `_SqliteConnWrapper` does not auto-rollback.

## Proposed fix (smallest correct design, in the wrapper only)

Track open savepoint names in `_PgConnWrapper` as a stack (`self._savepoints: list[str]`).

- `execute()` classifies the SQL with one case-insensitive regex on the leading tokens: `SAVEPOINT n`, `RELEASE [SAVEPOINT] n`, `ROLLBACK TO [SAVEPOINT] n`.
- After the statement succeeds: SAVEPOINT pushes n. RELEASE pops n and everything above it. ROLLBACK TO pops everything above n but keeps n (PostgreSQL keeps the savepoint after ROLLBACK TO).
- On exception: if the stack is non-empty, skip the whole-transaction rollback (the transaction stays aborted but recoverable, so the caller's ROLLBACK TO works). If the stack is empty, roll back exactly as today.
- `commit()`, `rollback()` and `close()` clear the stack. `close()` already rolls back first, so a leaked savepoint can never poison the pool.

Why a stack and not a counter: ROLLBACK TO an outer savepoint destroys inner ones, so a counter would drift and could suppress the safety rollback on that connection until the next commit. The stack costs a few lines more and stays correct under nesting.

Alternatives rejected:
- Context manager at each call site: user asked for a root fix, leaves raw `SAVEPOINT` SQL as a trap for every future caller.
- Implicit savepoint around every statement: extra round trip per statement and changes error semantics everywhere.
- Drop the auto-rollback entirely: reintroduces "current transaction is aborted" cascades in the many call sites that rely on it.
- Ask the server which savepoints are open: PostgreSQL offers no cheap way to list them.

## Scope state (search_path, app.* settings)

`set_tenant`, `set_rls_context`, `set_rls_bypass` use `self._conn.cursor()` directly, not `execute()`, so they never touch the savepoint stack.
They run before request work, when no savepoint is open, so `ROLLBACK TO SAVEPOINT` cannot revert them (a ROLLBACK TO only reverts SETs made after that savepoint).
The no-savepoint error path is unchanged, so the other worktree's commit-immediately change (claude/infallible-swartz-5f7f65) still covers it.
Expect only a textual neighbourhood overlap in database.py (execute, commit, rollback), no logical conflict.

## Tests to write FIRST (oneforall/tests/test_postgres_init.py, real-PG lane, must fail before the fix)

(a) Readiness: patch `data_service._RULES` with a good rule followed by a rule that runs a failing SQL through `db.execute`.
    The good rule MUST come first, because its finding upsert happens between rules and is the uncommitted work that gets lost.
    Assert after commit, read on a fresh connection, that the good rule's finding persists and `counts["failed_rules"]` names the bad rule.
(b) Bulk action: `execute_bulk_action` with three ids, the middle one's `execute_fn` runs a failing SQL through `db.execute`.
    Assert the other two are applied and persisted and the failed one is in `skipped`. Check the audit_log FK needs (user, org) when building the actor.
(c) Wrapper-level repro of the user's probe: INSERT, SAVEPOINT, failing SELECT via execute, ROLLBACK TO, commit, row survives.
    Also: nested savepoints (outer ROLLBACK TO then inner name is gone), and a failure with NO savepoint still rolls the whole transaction back.
(d) Scope survival: set_tenant plus set_rls_context, then a savepoint failure and ROLLBACK TO; assert `current_schema()` and `current_setting('app.current_org_id')` are unchanged.

## How to run (real-PG lane)

Database name must start with `themisiq_test_`. The postgres:18 image is cached locally, do not pull. Start Docker Desktop first if the daemon is down.

```bash
docker run -d --name themisiq-pg-test -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=themisiq_test_savepoint -p 127.0.0.1:55432:5432 postgres:18
```

From the oneforall directory, with `THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1` and `TEST_DATABASE_URL=postgresql://postgres:pg@localhost:55432/themisiq_test_savepoint` set, use the repo venv:

```bash
"C:\Projects\One For All\One For All\.venv\Scripts\python.exe" -m pytest tests/test_postgres_init.py -v
```

Then the full suite with the same interpreter, without the two env vars: `-m pytest` from oneforall (the global Python silently skips tests/ui).

## Change log

- 2026-10-07: Read database.py `_PgConnWrapper` (lines 240-373), both call sites, and the test module header and `pg` fixture. Created this plan. No code, test or config change. Nothing run (usage limit reached).

## Next steps

1. Start Docker, run the container above.
2. Write tests (a) to (d), run them, confirm each of (a) to (c) fails for the stated reason (InvalidSavepointSpecification, lost rows).
3. Implement the wrapper change in oneforall/database.py.
4. Re-run the PG lane, then the full suite, and log results here.
5. Do not commit or push without the user's go-ahead.
