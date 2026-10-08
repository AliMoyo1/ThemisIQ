# Integrate the changes made in parallel chats (2026-10-08)

Status: integrated and verified (2026-10-08); waiting for a decision on committing. Nothing here is committed or pushed. The other chats' worktrees under `.claude/worktrees/` are read only for this job: changes are copied into this working tree, never edited in place.

## What the other chats left (all uncommitted, all based on eec119f)

| Worktree (branch) | Topic | State found |
| --- | --- | --- |
| infallible-swartz-5f7f65 | PG session state (tenant `search_path`, RLS settings) lost on rollback | COMPLETE per its plan: `set_tenant`, `set_rls_context`, `set_rls_bypass` commit straight after their SETs; 5 real-PG tests + 1 SQLite test; full suite 1321 passed |
| amazing-brattain-42ceb5 | Pooled connection returned dirty by `provision_tenant_schema` and `_migrate_all_tenant_schemas` | INCOMPLETE: two real-PG tests drafted, never run; fix not applied |
| zealous-mcnulty-7b2cde | `execute()` rollback destroys PG savepoints (readiness rules, saved-view bulk actions) | PLAN ONLY: design written, no code or tests |
| affectionate-allen-5b5211 | Removed (soft-deleted) evidence links still counted outside the Vault | Code + tests in worktree |
| awesome-curran-511a92 | Topbar search portable case-insensitive LIKE (`core/sql_like.py`) | Code + tests in worktree |
| vibrant-lederberg-c0bd64 | Ask ARIA index scoping (org and business unit in the index, pre-filter) | Code + tests + rebuild script in worktree |
| xenodochial-wilson-ce5658 | AI thinking-trace widget | Already a commit (5b650fb) on its own branch; unrelated, left alone |
| amazing-brattain, others | Docs only (`plans/ROADMAP-2026-10.md`, CISO Assistant assessment, `plans/README.md`) | Already in this tree as untracked or modified files; not part of this job |

## Order and why

1. **Session-state fix, then the dirty-pool fix, together.** The session-state fix makes `set_rls_bypass()` commit immediately. `provision_tenant_schema()` and `_migrate_all_tenant_schemas()` call it and then hand the connection back with only `rollback()`, so after the first fix the bypass setting is committed on the pooled connection every time, not only when a tenant schema exists. The second fix (`wrapper.close()` in their `finally` blocks) must land with it.
2. **Savepoint-aware `execute()`** (design in zealous-mcnulty's plan), after 1, because it edits the same class.
3. **Removed-links readers, portable LIKE, Ask ARIA scoping.** Reconcile with my Evidence Vault Phase 1a work where files overlap (`routes_platform.py`, `test_postgres_init.py`, `grid/data_service.py`, `bcm/routes.py`).
4. Whole-suite verification: SQLite suite, the real-PG lane (Docker, cached `postgres:18`, see the test-environment memory), and the browser suite.

## Rules for this job

- Reproduce a defect on real PostgreSQL before fixing it where the other chat has not already shown it red; keep or add a real-PG regression test for every PG-layer change.
- Review each diff, not just apply it: security first (scope, RLS, pool hygiene), then correctness, then size.
- No commit, no push, no deployment. No em dashes in text or comments.

## Change log

2026-10-08, step 1 (PG layer, part 1).

- Backed up 41 uncommitted files first (scratchpad `backup_before_merge`). Wrote `merge3.py` (3-way merge per file against HEAD, keeps this tree's line endings) because five chats edited `tests/test_postgres_init.py`.
- Merged from infallible-swartz: `database.py` (the three scope setters commit at once), `tests/test_infrastructure_reliability.py`, five real-PG tests in `tests/test_postgres_init.py`, its plan file. Merged from amazing-brattain: two pool-return tests and its plan file. One textual conflict (both appended before the same test); resolved by taking each block whole.
- Real PostgreSQL 18.6 (throwaway container `themisiq-pg-test-integ`, cached image): with only the session-state fix, the two pool-return tests FAIL (`search_path` left as `tenant_contamorg, public` on the same backend pid), everything else passes. This confirms the coupling: the session-state fix commits the bypass setting, so provisioning and the startup migration now leak it every time.
- Fix in `database.py`: `provision_tenant_schema` and `_migrate_all_tenant_schemas` now call `wrapper.close()` in `finally` (rollback, reset search_path and app.* settings, commit, return to pool, or discard the connection if the reset fails) and make the bypass call inside the `try`, so a failure there can no longer strand the connection.
- GREEN: real-PG lane plus `test_infrastructure_reliability.py`: 29 passed, 0 failed.

2026-10-08, step 2 (PG layer, part 2: savepoints). No code existed in zealous-mcnulty's worktree, only its design; implemented here.

- Tests first. Six real-PG tests in `tests/test_postgres_init.py`: wrapper keeps pre-savepoint work after a failed statement; no-savepoint failure still rolls everything back (pins old behaviour); nested savepoints and an unrecoverable bad `ROLLBACK TO`; scope survives a failure inside a savepoint; `run_rules_for_org` keeps an earlier rule's finding when a later rule fails; `execute_bulk_action` applies the other ids when one fails. RED on the unmodified wrapper: the four savepoint-dependent tests fail with the reported error `InvalidSavepointSpecification: savepoint "..." does not exist`, including the two real call sites (readiness rules, saved-view bulk actions).
- Fix in `_PgConnWrapper` (`database.py`): `execute()` recognises `SAVEPOINT`, `RELEASE [SAVEPOINT]` and `ROLLBACK TO [SAVEPOINT]` with one regex, keeps a stack of open savepoint names, and skips its whole-transaction rollback when a savepoint is open (the caller's `ROLLBACK TO` recovers the transaction). A failing savepoint statement, or a failure with no savepoint open, rolls back exactly as before. `commit()`, `rollback()`, `close()` and the three scope setters clear the stack (the setters now call `self.commit()` instead of the raw connection so the bookkeeping cannot go stale).
- Five fast tests with a fake raw connection added to `tests/test_infrastructure_reliability.py` (default suite). Against the original `database.py` 5 of the 6 fake-connection tests fail (the session-state one plus four savepoint ones; the sixth pins old behaviour).
- GREEN: real-PG lane plus reliability tests: 35 passed, 0 failed.

2026-10-08, step 3a (removed-links readers, from affectionate-allen).

- Clean 3-way merge. Seven readers outside the Vault counted soft-deleted `evidence_links` rows (ARIA two queries, BCM two evidence lists, ERM `list_risk_controls`, governance effectiveness two queries, GRID `attach_vault_item_to_grid_control` existing-link check); each now adds `deleted_at IS NULL`. New `tests/test_removed_links_outside_vault.py`; `tests/test_governance_controls.py` hand-made schema gets the column.
- GREEN with the Vault Phase 1a tests: no failures.
- Not fixed here (allen's own notes): the Vault module does not recompute control effectiveness when a link is removed, and a GRID-first re-attach can leave a removed link behind.

2026-10-08, step 3b (portable topbar search, from awesome-curran).

- New `core/sql_like.py` (`like_pattern`, `ci_like`) and `tests/test_global_search_like.py`; `routes_platform.py` merged without conflicts (14 blocks converted to `LOWER(col) LIKE LOWER(%s) ESCAPE '!'`, the user's `%`, `_` and `!` made literal, term capped at 200 characters). One more real-PG test (case and wildcard behaviour) added to `tests/test_postgres_init.py`; one textual conflict there resolved by keeping both sides whole.
- Follow-ups made here: `evidence/scope.py` no longer carries its own copy of the LIKE helpers (it builds its predicate with `ci_like`, so there is one definition of the escape character and the term cap); removed the unused `search_term` in `api_global_search`; the risk register block called `r.get(...)` which does not exist on SQLite rows (RED: `AttributeError: 'sqlite3.Row' object has no attribute 'get'` once the test's `sqlite3.Row` subclass workaround was removed), now `r["source_module"] or ""`.
- GREEN: search, scope, Vault read and removed-link tests: 54 passed; real-PG lane plus reliability tests: 41 passed, 0 failed, 0 skipped.

2026-10-08, step 3c (Ask ARIA index scoping, from vibrant-lederberg).

- Reviewed the diff before merging (security first). Sound: org and business unit live in the index and are filtered in SQL before ranking and the top-k cut; `_scope_sql` mirrors `document_scope_sql` / `document_read_ok` (`bu_scope_ids` returns `[-1]`, never `[]`, so there is no empty `IN ()`); the live-row document check stays as defense in depth; `_clear_by` calls `init_index()` so every write path targets the current tenant schema instead of falling through `search_path` to `public`; search errors are no longer swallowed into "no policy covers this".
- Merged cleanly (`ask_service.py` was untouched here; `test_postgres_init.py` merged without conflict). New: `tests/test_aria_ask_scoping.py` (18 tests), `scripts/rebuild_ask_index.py`, four real-PG tests.
- Made stale by step 1: the "no retry because the rollback discards the tenant SET" reasoning in `_search_pg` and one test docstring, and a comment in a PG test about provisioning leaving a dirty pooled connection. Comments corrected; behaviour (a failed query raises, no wider fallback) kept.
- Added here: tests for the rebuild script (two SQLite, one real-PG; the chat had none) and an entry for it in `docs/aria-policy-authoring.md` section 7.
- RED on the merged tree: with the original `ask_service.py` swapped in, all 4 real-PG Ask ARIA tests fail, the first on the leak itself (the default org's own chunk wiped by a tenant's `reindex_document` through the `public` fall-through, so its question found nothing). Fixed file restored afterwards.
- GREEN: SQLite (Ask scoping, ARIA policy legacy and publication, reliability) 93 passed; real-PG lane 34 passed before the script tests were added, script test passes.
- Found by reading and then confirmed on real PostgreSQL (probe, then test): `rebuild_index()` drops `aria_ask_index` through `search_path`, so run from a tenant with no table of its own it dropped the shared `public` one (the default organization's index). It is an operator function, not wired to a route, but the damage was cross-tenant. RED: new real-PG test `test_rebuild_index_from_a_tenant_never_drops_the_shared_public_index_on_real_postgres` failed with `(False, True)`. Fix: `rebuild_index()` calls `init_index()` first, so the tenant's own table exists and is the one the DROP resolves to. GREEN.
- Left alone and reported: the Ask page header count (`aria/routes.py`) is not scoped (a number only).

2026-10-08, step 4 (whole-tree verification, repo venv, run from oneforall/).

- Backend, SQLite plus the real-PG lane on PostgreSQL 18.6 (`pytest tests --ignore=tests/ui`): **1008 passed, 0 failed, 0 skipped** in 10m41s. Before this job HEAD had 914 tests with 15 PG skips.
- Browser suite (`pytest tests/ui`): **411 passed, 2 skipped, 0 failed** in 17m51s. Both skips are intentional and unrelated: `auth.login.submit` is reachable while logged out, and the chip-filter fixture seeds no document rows.
- Throwaway container `themisiq-pg-test-integ` removed. The other chats' worktrees under `.claude/worktrees/` are untouched and can be removed once this is committed.

Not verified: RLS row filtering (the lane's `postgres` user is a superuser, and `core/rls.py` notes the application role must be NOSUPERUSER and NOBYPASSRLS for RLS to apply at all), anything on the production VPS, and the extra round trips per tenant `get_db()` (each scope setter now ends with a COMMIT).

Open, reported and not fixed here:
- Related Items and topbar search still show other business units' titles: 13 of the 14 search blocks have no org or BU filter, and about 39 more plain LIKE lines in 13 files are unscoped (the live PLAN-37 exposure).
- `get_cross_module_profile` ignores the viewer's scope.
- About 58 sites catch a DB error and carry on (worst: `modules/launcher/routes_dashboard.py`, 14).
- Ask ARIA page header count is unscoped (a number only).
- Control effectiveness is not recomputed when an evidence link is removed in the Vault module; a GRID-first re-attach can leave a removed link behind.

Deploy note: run `scripts/rebuild_ask_index.py` once after deploying the Ask ARIA change (stamps control and risk chunks per tenant and clears stray rows from the shared `public` table).
