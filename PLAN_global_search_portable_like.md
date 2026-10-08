# PLAN: portable LIKE in the topbar global search

Status: COMPLETE (nothing committed, nothing pushed)
Worktree: awesome-curran-511a92, branch claude/nifty-burnell-80ec8c, base eec119f
Scope: oneforall/modules/launcher/routes_platform.py `api_global_search` only.
Not in scope: which tables are searched, or their org / business unit scoping.

## Goal

Every `col LIKE %s` in `api_global_search` becomes
`LOWER(col) LIKE LOWER(%s) ESCAPE '!'` with the term escaped by `like_pattern`,
so the same rows match on SQLite (tests) and PostgreSQL (production).
PostgreSQL LIKE is case sensitive; SQLite LIKE is not. The user's own `%`, `_`
are wildcards on both engines today.

## Finding that shaped the approach

The evidence conversion described in the brief (`modules/evidence/scope.py`,
`evidence_search_sql`, `like_pattern`) is UNCOMMITTED work in the main checkout
(`git status` there: `?? oneforall/modules/evidence/scope.py`, `M routes_platform.py`,
`M test_postgres_init.py`, `?? tests/test_evidence_vault_reads.py`). This worktree is
cut from the committed HEAD eec119f, so none of it exists here. `git log --all -S evidence_search_sql`
finds nothing on any branch.

## Decisions

1. Generic helper goes in a new `oneforall/core/sql_like.py` (`like_pattern`, `ci_like`),
   the "core/ if cleaner" option in the brief. `like_pattern` is byte-for-byte the same
   behaviour as scope.py's so the vault work can later import it instead of keeping a copy.
   scope.py itself is NOT copied here and the main checkout is NOT touched.
2. The old evidence block stays exactly as it is (it is superseded by the main checkout's
   version). It still needs the unescaped `%term%`, so `search_term` stays for it and the
   converted blocks use a new `like_term`. After the vault work is merged, `search_term` is
   unused and its line can be deleted.
3. Predicate is `LOWER(col) LIKE LOWER(%s) ESCAPE '!'` as specified (no COALESCE; it makes no
   difference for a positive match in WHERE).
4. SQLite tests run with `PRAGMA case_sensitive_like = ON`, which makes plain LIKE case
   sensitive like PostgreSQL, so the case tests fail on the old code instead of passing by luck.
5. `sqlite3.Row` has no `.get`, and the risk register block calls `r.get(...)`, so that block
   raises on SQLite for any matching row (PostgreSQL rows have `.get`). Production code is not
   changed for this; the test fixture gives its rows `.get`. Reported as a finding.

## Files

- NEW  oneforall/core/sql_like.py
- EDIT oneforall/modules/launcher/routes_platform.py (14 blocks, 21 predicates)
- NEW  oneforall/tests/test_global_search_like.py (SQLite lane)
- EDIT oneforall/tests/test_postgres_init.py (one TEST_DATABASE_URL lane test, appended after
  test_warm_replay_queries_execute_on_real_postgres to avoid the hunk the main checkout edits)

## Steps and log

(each change is logged here as it lands)

[done] oneforall/core/sql_like.py: new. like_pattern (same behaviour as scope.py) and ci_like (validated column name).
[done] oneforall/tests/test_global_search_like.py: new, 9 tests. Seeds one hit and one decoy row per searched column
       in all 14 blocks (21 predicates). Runs with PRAGMA case_sensitive_like = ON.
[done] red run against the UNMODIFIED route: 4 failed (case, % , _, aria scope since it uses a mixed case term),
       5 passed. escape-character and backslash cases pass on old code by design: they guard the new helper.
       (first red run was invalid: `assert _found(t) == _seed(...)` searched before seeding; fixed the order.)
[done] oneforall/modules/launcher/routes_platform.py:13,107-108,110-245: import ci_like/like_pattern; new `like_term`;
       21 predicates in 14 blocks now `ci_like('col')`. Evidence block untouched (still uses `search_term`).
[done] green run: tests/test_global_search_like.py 9 passed.
[done] mutation check on a scratchpad copy: 21 predicates x 2 mutants (bare LIKE; LOWER without ESCAPE) = 42 killed, 0 survived.
[done] oneforall/tests/test_postgres_init.py: new test_global_search_ignores_case_and_treats_wildcards_literally_on_real_postgres,
       inserted after test_warm_replay_queries_execute_on_real_postgres. NOT executed here: no PostgreSQL, Docker daemon off,
       TEST_DATABASE_URL unset. Its body was dry-run against SQLite with case_sensitive_like on (seed SQL, expected sets, handler call).
[info] database.LIKE_OP (ILIKE on PG) exists at database.py:34 but nothing uses it.
[done] tests/ui/test_premium_shell_controls.py (types "risk" into the real search box, hits /api/search): 10 passed.
[done] differential: old handler (git show HEAD) vs new, same seeded SQLite DB, 17 ordinary terms: identical JSON every time.
[done] merge simulation on a scratchpad copy of the main checkout working tree: my patch applies with no conflicts
       (10 hunks, offsets only); with your vault tests + mine together: 45 passed, 17 skipped (PG lane), 0 failed.
       After merging, `search_term` in api_global_search is unused: delete that line and its comment.
[done] full non-UI suite in this worktree: 917 tests, 901 passed, 16 skipped (PG lane), 0 failed, 0 errors.

## Open items for the owner

1. Run the new PG lane test on a real PostgreSQL (not run here: no PostgreSQL, Docker daemon off, TEST_DATABASE_URL unset).
2. After the vault work is merged, delete `search_term` and its comment in api_global_search (unused by then).
3. Optional: make modules/evidence/scope.py import like_pattern and MAX_SEARCH_CHARS from core/sql_like.py so there is one copy.
4. Pre-existing, not touched: the risk register block calls r.get(...), which sqlite3.Row lacks, so that block raises on SQLite
   for any matching row (PostgreSQL is fine). One line fix if wanted: `_sm = r["source_module"] or ""`.
5. Pre-existing, not touched: about 39 other plain `LIKE %s` lines in 13 other files (see PG_MIGRATION_AUDIT.md H3).
6. Separate audit: only aria_documents has an org / BU filter in this search; 13 blocks have none.

[info] RLS exists only in core/rls.py on 10 tables; of the global search tables only evidence_items. None of the 14
       converted tables has a policy, and only aria_documents has an org / BU filter in the SQL.
