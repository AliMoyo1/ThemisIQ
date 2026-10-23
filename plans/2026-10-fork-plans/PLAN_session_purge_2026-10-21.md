# PLAN: purge expired rows from the `sessions` table (2026-10-21)

Goal: `cleanup_expired_sessions()` in `oneforall/core/auth.py` was defined but never called. Expired rows in
`sessions` are only removed lazily, when that exact token is presented again (`get_session_user`), so rows of
browsers that never come back stay forever. Run the purge from the app's own scheduler: once at startup, then hourly.

## Findings (read before building)

- Scheduler convention: one module per scheduler in `core/` or `modules/*/`, each with `start_scheduler()` and
  `stop_scheduler()`, a module level `BackgroundScheduler`, registered inside `try/except` blocks in
  `main.py` startup and shutdown. Closest sibling: `core/event_sweeper.py` (`run_once()` returns counts, logs, never raises).
- Lock convention: `database.try_acquire_scheduler_lock(db, name, lease_seconds)` (cross-process lease in
  `scheduler_locks`). The systemd unit runs ONE process (`scripts/systemd/themisiq-app.service`, `--workers 1`, on
  purpose per `scripts/PRODUCTION_DEPLOYMENT.md`); the Docker entrypoint defaults to 2 workers, each with its own
  scheduler. The code comments that say "scripts/deploy.py: --workers 2" are stale. On the VPS the lease is
  redundant but harmless (one tiny upsert per hour); it matters for the Docker topology.
- `sessions` is declared only in `_SHARED_TABLES` (public schema, never in tenant schemas) and has NO row level
  security policy in `core/rls.py` (it also has no `org_id` column for the standard policy to use).
- `expires_at` is TEXT. Production writers are only `create_session` and `promote_mfa_session`, both
  `utcnow().isoformat()` (naive UTC, `T` separator), so a Python supplied `utcnow().isoformat()` bound parameter
  compares correctly. `datetime('now')` / `CURRENT_TIMESTAMP` use a space separator and break same-day comparisons.
- No table references `sessions(id)`, so deleting rows has no foreign key effect.
- No backend test runs the app startup handler; the UI harness (`tests/ui/conftest.py`) does, on a temp SQLite file.

## Files to touch

- `oneforall/core/auth.py`: `cleanup_expired_sessions()` uses the RLS bypass connection and returns the number removed.
- `oneforall/core/session_sweeper.py` (new): `run_once()`, `start_scheduler()`, `stop_scheduler()`.
- `oneforall/main.py`: start in `startup()`, stop in `shutdown()`, same shape as the other schedulers.
- `oneforall/tests/test_session_sweeper.py` (new): backend tests.

## Approach and decisions

1. Reuse, no new dependency: APScheduler `BackgroundScheduler` (already pinned), `IntervalTrigger(hours=1)`,
   `try_acquire_scheduler_lock`. The first run is the job's own `next_run_time=now`, so "once at startup" runs in the
   scheduler thread and never delays startup. Same job id means one registration, not two.
2. Lock lease 300 s: covers the start skew between workers (they tick at the same offsets), far below the one hour
   interval so a crashed holder never blocks the next run. The DELETE is idempotent, so the lock only saves duplicate
   work; it is not a correctness requirement. Kept because the brief asks to reuse the lock convention.
3. Connection: `get_db_bypass_rls()`. `sessions` has no policy today, so a plain connection would also work, but a
   policy added later would make a plain connection delete zero rows silently (RLS filters DELETE rows without an
   error), which is the very bug being fixed. A global maintenance job with no request or org context is what the
   bypass connection is documented for (same as session validation).
4. MFA pending logins: untouched beyond their normal expiry (ordinary rows, 10 minute TTL). No special case in SQL.
5. No batching, no index on `expires_at`: after the first purge the table holds live sessions only (YAGNI).

## Change log

- [done] oneforall/core/auth.py `cleanup_expired_sessions` : now `get_db_bypass_rls()`, returns `rowcount`; docstring says why (bypass, TEXT isoformat comparison)
- [done] oneforall/core/session_sweeper.py (new) : `run_once()` (lease via `try_acquire_scheduler_lock`, never raises, returns count), `start_scheduler()` (hourly, first run at start through `next_run_time`), `stop_scheduler()`
- [done] oneforall/main.py : sweeper started after the event sweeper in `startup()`, stopped last in `shutdown()`, same try/except shape as its neighbours
- [done] oneforall/tests/test_session_sweeper.py (new) : 6 tests (data semantics on a fixed clock, job count, lease held and expired, failure logged, real scheduler purges at startup, main.py wiring guard)
- [done] oneforall/tests/test_postgres_init.py : one real-PG lane test, `test_expired_sessions_are_purged_and_the_lease_holds_on_real_postgres`, placed after the event sweeper lane test (mid-file, not at the end where parallel sessions append)
- [done] oneforall/core/session_sweeper.py docstring : corrected the worker topology (systemd one process, Docker entrypoint several)
- [done] new files converted to CRLF to match the working tree (`core.autocrlf=true`); nothing staged, nothing committed

## Verification (2026-10-21)

- `tests/test_session_sweeper.py`: 6 passed.
- Mutation checks (each restored byte identical, hash checked): space-separator comparison fails 2 tests (only 2 of the 5
  expired rows go, so the same-day case is covered); lease ignored fails the lease test; main.py wiring removed fails the
  wiring guard; `next_run_time` removed fails the scheduler test after its 10 s wait.
- Real `main.startup()` and `main.shutdown()` on a throwaway SQLite file: job registered (1 h interval), the startup
  run removed the 2 expired of 4 seeded rows, the scheduler stopped on shutdown.
- Real PostgreSQL 18.6 (collation `en_US.utf8`, throwaway container, removed afterwards): the new lane test passed.
  Only that one test was run, not the whole lane file.
- Full backend suite (`pytest tests --ignore=tests/ui`): 2669 passed, 76 skipped (the 76 real-PG lane tests, off by
  default, mine included), 0 failed, 50 minutes (much longer than the old 10 minute note: the suite has grown to 2669
  tests, and other sessions were running their own pytest at times).
- `python scripts/capability_inventory.py --check`: matches (no routes touched).
- UI harness smoke (`tests/ui/test_harness_smoke.py`, own pytest session, boots the real app so the new scheduler starts
  in it, real browser login, navigation, modal and API call): 1 passed in 21 s, no skips. The whole `tests/ui` suite was not run.

## Not done / for the owner

- Not committed, not pushed, not deployed. After deploy, `journalctl -u themisiq-app.service` shows the line
  "Session sweeper started" at boot and "Session purge: removed N expired session(s)" on the first run (N is the backlog).
- The first run after deploy deletes the whole backlog in one statement (no batching, by design).
- `oneforall/ARCHITECTURE.md` tree not updated (it already omits the event sweeper).
